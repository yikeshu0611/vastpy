"""
Drive the Vast large-file viewer from Python.

Mirrors the R package ``vastR`` against the same localhost JSON API.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any, Iterable, Sequence

import pandas as pd

from . import client as _c

__version__ = "0.6.34"

# Re-export connection helpers (R: vast_is_running, vast_log_path, …)
is_running = _c.is_running
log_path = _c.log_path
api_info = _c.api_info
ensure = _c.ensure


def _abs(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve())


def _read_path(path: str | Path, delim: Any = "\t", header: int = 1) -> pd.DataFrame:
    has_header = int(header or 0) > 0
    sep = "\t"
    d = _c.normalize_delim(delim) or delim
    if d in (",",) or str(d).lower() in ("comma", "csv"):
        sep = ","
    elif d in ("tab", "\t") or str(d).lower() == "tsv":
        sep = "\t"
    elif d is not None and str(d) != "":
        sep = str(d)
    return pd.read_csv(
        path,
        sep=sep,
        header=0 if has_header else None,
        dtype=str,
        keep_default_na=False,
        quotechar='"',
        engine="c",
    )


def _peek_column_names(header: int = 1) -> list[str]:
    hdr = max(0, int(header))
    try:
        df = read(from_line=hdr + 1, n=1)
    except Exception:
        return []
    return list(df.columns.astype(str))


class VastTbl:
    """Handle for a file open in Vast (like R ``vast_tbl``)."""

    def __init__(
        self,
        path: str,
        columns: Sequence[str] | None = None,
        delim: str | None = None,
        header: int | None = None,
        status: dict[str, Any] | None = None,
        select: Sequence[str] | None = None,
        indexes: Sequence[str] | None = None,
        index_paths: dict[str, str] | None = None,
    ):
        self.path = path
        self.columns = list(columns or [])
        self.delim = delim
        self.header = int(header) if header is not None else 0
        self.status = status or {}
        self.select = list(select) if select is not None else None
        self.indexes = list(indexes or [])
        self.index_paths = dict(index_paths or {})

    def __repr__(self) -> str:
        st = self.status or {}
        lines = st.get("lines", "?")
        indexing = " (indexing…)" if st.get("indexing") else ""
        delim = st.get("delim_name") or st.get("delim") or self.delim or "?"
        cols = ", ".join(self.columns) if self.columns else "(unknown)"
        idx = ""
        if self.indexes:
            idx = f"\n  indexes: {', '.join(self.indexes)} (attached)"
        elif st.get("attached_indexes"):
            nms = [
                str(a.get("column_name") or "")
                for a in st["attached_indexes"]
                if isinstance(a, dict)
            ]
            if any(nms):
                idx = f"\n  indexes: {', '.join(n for n in nms if n)} (attached)"
        return (
            f"<vastpy.VastTbl>\n"
            f"  path: {self.path}\n"
            f"  lines: {lines}{indexing}\n"
            f"  delim: {delim}  header: {self.header}\n"
            f"  columns: {cols}{idx}"
        )

    def __len__(self) -> int:
        st = self.ensure()
        lines = st.get("lines")
        if lines is None:
            return 0
        return max(0, int(lines) - int(self.header or 0))

    @property
    def shape(self) -> tuple[int, int]:
        return (len(self), len(self.columns))

    def ensure(self) -> dict[str, Any]:
        st = _c.request("GET", "/v1/status")
        cur = str(st.get("path") or "")
        want = _abs(self.path)
        same = bool(cur) and _abs(cur) == want
        api_delim = _c.delim_for_api(self.delim)
        if not same:
            body: dict[str, Any] = {"path": want, "activate": False}
            if api_delim is not None:
                body["delim"] = api_delim
            if self.header is not None:
                body["header"] = int(self.header)
            st = _c.request("POST", "/v1/open", body)
        elif api_delim is not None or self.header is not None:
            body = {}
            if api_delim is not None:
                body["delim"] = api_delim
            if self.header is not None:
                body["header"] = int(self.header)
            if body:
                st = _c.request("POST", "/v1/layout", body)
        st = _c.request("GET", "/v1/status")
        delim_name = str(st.get("delim_name") or "").lower()
        if (
            api_delim
            and not str(st.get("delim") or "")
            and delim_name not in ("tab", "comma")
        ):
            st = _c.request(
                "POST",
                "/v1/layout",
                {"delim": api_delim, "header": int(self.header or 1)},
            )
        self.status = st
        return st

    def _apply_select(self, df: pd.DataFrame) -> pd.DataFrame:
        if not self.select:
            return df
        keep = [c for c in self.select if c in df.columns]
        return df.loc[:, keep] if keep else df.iloc[:, 0:0]

    def head(self, n: int = 6) -> pd.DataFrame:
        st = self.ensure()
        hdr = max(0, int(st.get("header") if st.get("header") is not None else self.header or 0))
        n = max(1, int(n))
        return self._apply_select(read(from_line=hdr + 1, n=n))

    def to_frame(self, n: int = 100) -> pd.DataFrame:
        return self.head(n=n)

    def select(self, *columns: str) -> VastTbl:
        if not columns:
            raise ValueError("select() 需要至少一个列名")
        keep = list(columns)
        return VastTbl(
            path=self.path,
            columns=keep,
            delim=self.delim,
            header=self.header,
            status=self.status,
            select=keep,
            indexes=self.indexes,
            index_paths=self.index_paths,
        )

    def filter(
        self,
        column: str,
        op: str = "==",
        value: Any = None,
        *,
        max_rows: int | None = None,
        from_line: int | None = None,
        to_line: int | None = None,
        open_in_vast: bool = False,
        collect: bool = True,
        ignore_case: bool = True,
    ) -> pd.DataFrame | dict[str, Any]:
        """Filter rows (full-file scan or via attached index)."""
        self.ensure()
        if value is None and op not in ("==",):
            raise ValueError("filter 需要 value")
        out = _filter_exec(
            column=column,
            value=value,
            op=op,
            max_rows=max_rows,
            from_line=from_line,
            to_line=to_line,
            open_in_vast=open_in_vast,
            collect=collect,
            ignore_case=ignore_case,
        )
        if isinstance(out, pd.DataFrame):
            return self._apply_select(out)
        return out

    def sort(
        self,
        column: str | int,
        order: str = "asc",
        type: str = "auto",
        path: str | Path | None = None,
        na_last: bool = True,
        max_rows: int = 0,
    ) -> VastTbl:
        return sort(
            self,
            column=column,
            order=order,
            type=type,
            path=path,
            na_last=na_last,
            max_rows=max_rows,
        )

    def unique(self) -> pd.DataFrame:
        self.ensure()
        cols = self.columns
        if not cols:
            raise ValueError("没有列可取唯一值，请先 select()")
        path = str(_c.cache_path())
        _c.request("POST", "/v1/unique", {"columns": list(cols), "path": path}, timeout=3600)
        return _read_path(path, "\t", 1)

    def distinct(self, *columns: str) -> pd.DataFrame:
        t = self.select(*columns) if columns else self
        return t.unique()

    def build_index(
        self, column: str | int, path: str | Path | None = None, force: bool = False
    ) -> str:
        return build_index(self, column, path=path, force=force)

    def attach_index(self, column: str | int, path: str | Path | None = None) -> VastTbl:
        return attach_index(self, column, path=path)

    def detach_index(self, column: str | int | None = None) -> VastTbl:
        return detach_index(self, column=column)

    def _resolve_index_path(self, path: str | Path) -> str:
        p = Path(path).expanduser()
        if p.is_absolute():
            return str(p.resolve())
        base = Path(self.path).resolve().parent
        return str((base / p).resolve())


def _new_tbl(
    status: dict[str, Any],
    col_names: Sequence[str] | None = None,
    delim: str | None = None,
    header: int | None = None,
) -> VastTbl:
    path = status.get("path")
    if not path:
        raise RuntimeError("Vast 未打开文件")
    if delim is None:
        delim = str(status.get("delim") or "")
        dn = str(status.get("delim_name") or "").lower()
        if not delim and dn in ("tab", "tsv"):
            delim = "tab"
        if not delim and dn in ("comma", "csv"):
            delim = ","
        if delim == "\t":
            delim = "tab"
    if header is None:
        header = int(status.get("header") or 0)
    if not col_names:
        col_names = _peek_column_names(int(header))
    return VastTbl(
        path=str(path),
        columns=list(col_names),
        delim=delim,
        header=int(header),
        status=status,
    )


def open(
    path: str | Path,
    delim: Any = None,
    header: int | None = None,
    tail_bytes: int | None = None,
) -> VastTbl:
    """Open a file in Vast and return a ``VastTbl`` handle."""
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"文件不存在: {p}")
    body: dict[str, Any] = {"path": _abs(p), "activate": False}
    nd = _c.normalize_delim(delim)
    if nd is not None:
        body["delim"] = _c.delim_for_api(nd) or nd
    if header is not None:
        body["header"] = int(header)
    if tail_bytes is not None:
        body["tail_bytes"] = int(tail_bytes)
    status = _c.request("POST", "/v1/open", body)
    tmp = _new_tbl(status, col_names=[], delim=nd, header=header)
    tmp.ensure()
    status = _c.request("GET", "/v1/status")
    cols = _peek_column_names(tmp.header if tmp.header is not None else 1)
    return _new_tbl(status, col_names=cols, delim=tmp.delim, header=tmp.header)


def view(x: Any, title: str | None = None, **kwargs: Any) -> VastTbl:
    """Open a path, or write a DataFrame/dict to a temp TSV and open it."""
    if isinstance(x, (str, Path)) and Path(x).expanduser().exists():
        return open(x, **kwargs)
    if title is None:
        title = "data"
    if not isinstance(x, pd.DataFrame):
        x = pd.DataFrame(x)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", title) or "data"
    dir_ = Path(tempfile.gettempdir()) / "vastpy"
    dir_.mkdir(parents=True, exist_ok=True)
    path = dir_ / f"{safe}.tsv"
    x.to_csv(path, sep="\t", index=False, quoting=1)  # csv.QUOTE_ALL
    return open(path, delim="\t", header=1)


def status() -> dict[str, Any]:
    return _c.request("GET", "/v1/status")


def goto(line: int) -> dict[str, Any]:
    return _c.request("POST", "/v1/goto", {"line": int(line)})


def find(q: str, from_line: int | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"q": str(q)}
    if from_line is not None:
        body["from"] = int(from_line)
    return _c.request("POST", "/v1/find", body)


def layout(delim: Any = None, header: int | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {}
    nd = _c.normalize_delim(delim)
    if nd is not None:
        body["delim"] = nd
    if header is not None:
        body["header"] = int(header)
    if not body:
        raise ValueError("请提供 delim 或 header")
    return _c.request("POST", "/v1/layout", body)


def export(
    from_line: int,
    to_line: int,
    path: str | Path,
    include_header: bool = True,
) -> dict[str, Any]:
    body = {
        "from": int(from_line),
        "to": int(to_line),
        "path": str(Path(path).expanduser()),
        "include_header": bool(include_header),
    }
    return _c.request("POST", "/v1/export", body)


def read(from_line: int = 1, to_line: int | None = None, n: int = 100) -> pd.DataFrame:
    if to_line is None:
        to_line = int(from_line) + int(n) - 1
    path = _c.cache_path()
    meta = export(from_line, to_line, path, include_header=True)
    return _read_path(path, meta.get("delim"), meta.get("header", 1))


def build_index(
    x: VastTbl,
    column: str | int,
    path: str | Path | None = None,
    force: bool = False,
) -> str:
    if not isinstance(x, VastTbl):
        raise TypeError("需要 VastTbl（由 vastpy.open() 返回）")
    x.ensure()
    body: dict[str, Any] = {"column": column, "force": bool(force)}
    if path is not None and str(path):
        body["path"] = x._resolve_index_path(path)
    res = _c.request("POST", "/v1/index/build", body, timeout=3600)
    return str(res["path"])


def attach_index(
    x: VastTbl, column: str | int, path: str | Path | None = None
) -> VastTbl:
    if not isinstance(x, VastTbl):
        raise TypeError("需要 VastTbl（由 vastpy.open() 返回）")
    x.ensure()
    body: dict[str, Any] = {"column": column}
    if path is not None and str(path):
        body["path"] = x._resolve_index_path(path)
    res = _c.request("POST", "/v1/index/attach", body)
    cn = str(res.get("column_name") or column)
    indexes = list(dict.fromkeys([*x.indexes, cn]))
    index_paths = dict(x.index_paths)
    index_paths[cn] = str(res.get("path") or "")
    x.indexes = indexes
    x.index_paths = index_paths
    return x


def detach_index(x: VastTbl, column: str | int | None = None) -> VastTbl:
    if not isinstance(x, VastTbl):
        raise TypeError("需要 VastTbl（由 vastpy.open() 返回）")
    x.ensure()
    body: dict[str, Any] = {}
    if column is not None:
        body["column"] = column
    # Empty body must be {} not omitted weirdness — send explicit dict
    _c.request("POST", "/v1/index/detach", body if body else {})
    if column is None:
        x.indexes = []
    else:
        cn = str(column)
        x.indexes = [c for c in x.indexes if c != cn]
    return x


def sort(
    x: VastTbl,
    column: str | int,
    order: str = "asc",
    type: str = "auto",
    path: str | Path | None = None,
    na_last: bool = True,
    max_rows: int = 0,
) -> VastTbl:
    if not isinstance(x, VastTbl):
        raise TypeError("需要 VastTbl（由 vastpy.open() 返回）")
    order = order.lower()
    if order not in ("asc", "desc"):
        raise ValueError('order 应为 "asc" 或 "desc"')
    type = type.lower()
    if type not in ("auto", "string", "numeric"):
        raise ValueError('type 应为 "auto" / "string" / "numeric"')
    x.ensure()
    src = x.path
    cn = str(column)
    if path is None or not str(path):
        base = Path(src).stem
        path = Path(src).resolve().parent / f"{base}.sorted-{cn}.tsv"
    out_path = x._resolve_index_path(path)
    body = {
        "column": column,
        "path": out_path,
        "order": order,
        "type": type,
        "na_last": bool(na_last),
        "max_rows": max(0, int(max_rows or 0)),
    }
    meta = _c.request("POST", "/v1/sort", body, timeout=3600)
    if meta.get("via_index"):
        print(f"vastpy: sort via index  rows={meta.get('rows')}")
    else:
        print(f"vastpy: sort full scan  rows={meta.get('rows')} scanned={meta.get('scanned')}")
    hdr = int(meta.get("header") if meta.get("header") is not None else x.header or 1)
    out = open(out_path, delim="\t", header=hdr)
    out.status = {**(out.status or {}), "vast_sort": meta}
    return out


def _filter_exec(
    column: Any,
    value: Any,
    op: str = "==",
    max_rows: int | None = None,
    from_line: int | None = None,
    to_line: int | None = None,
    open_in_vast: bool = False,
    collect: bool = True,
    ignore_case: bool = True,
) -> pd.DataFrame | dict[str, Any]:
    path = str(_c.cache_path())
    op = str(op)
    if isinstance(value, (list, tuple)):
        vals = [str(v) for v in value if v is not None and not (isinstance(v, float) and pd.isna(v))]
    elif value is None:
        vals = []
    else:
        vals = [str(value)]
    if op == "in" or len(vals) > 1:
        op = "in"
        json_value: Any = vals
    else:
        json_value = vals[0] if vals else ""
    body: dict[str, Any] = {
        "column": column,
        "value": json_value,
        "op": op,
        "path": path,
        "open": bool(open_in_vast),
        "ignore_case": bool(ignore_case),
        "max_rows": int(max_rows) if max_rows and int(max_rows) > 0 else 0,
    }
    if from_line is not None:
        body["from"] = int(from_line)
    if to_line is not None:
        body["to"] = int(to_line)
    meta = _c.request("POST", "/v1/filter", body, timeout=3600)
    if meta.get("via_index"):
        print(f"vastpy: filter via index  matched={meta.get('matched')}")
    else:
        print(
            f"vastpy: filter full scan  matched={meta.get('matched')} "
            f"scanned={meta.get('scanned')}"
        )
    if open_in_vast:
        return meta
    if not collect:
        meta = dict(meta)
        meta["local_path"] = path
        return meta
    out = _read_path(path, meta.get("delim"), meta.get("header", 1))
    out.attrs["vast_filter"] = meta
    out.attrs["path"] = path
    return out


def filter(
    data: VastTbl | str,
    value: Any = None,
    op: str = "==",
    *,
    column: str | None = None,
    max_rows: int | None = None,
    from_line: int | None = None,
    to_line: int | None = None,
    open_in_vast: bool = False,
    collect: bool = True,
    ignore_case: bool = True,
) -> pd.DataFrame | dict[str, Any]:
    """
    Filter helper.

    Preferred::
        t.filter("col", "==", "val")
        filter(t, column="col", op="==", value="val")

    Legacy (R-style positional)::
        filter("col", "val", op="==")
    """
    if isinstance(data, VastTbl):
        if column is None:
            raise ValueError('用法: t.filter("col", "==", val) 或 filter(t, column=..., value=...)')
        return data.filter(
            column,
            op=op,
            value=value,
            max_rows=max_rows,
            from_line=from_line,
            to_line=to_line,
            open_in_vast=open_in_vast,
            collect=collect,
            ignore_case=ignore_case,
        )
    # Legacy: filter(column, value, op=...)
    col = data
    return _filter_exec(
        column=col,
        value=value,
        op=op,
        max_rows=max_rows,
        from_line=from_line,
        to_line=to_line,
        open_in_vast=open_in_vast,
        collect=collect,
        ignore_case=ignore_case,
    )


# R-style aliases
vast_open = open
vast_view = view
vast_status = status
vast_goto = goto
vast_find = find
vast_layout = layout
vast_read = read
vast_export = export
vast_is_running = is_running
vast_log_path = log_path
vast_build_index = build_index
vast_attach_index = attach_index
vast_detach_index = detach_index
vast_sort = sort
vast_filter = filter

__all__ = [
    "VastTbl",
    "open",
    "view",
    "status",
    "goto",
    "find",
    "layout",
    "read",
    "export",
    "filter",
    "sort",
    "build_index",
    "attach_index",
    "detach_index",
    "is_running",
    "log_path",
    "api_info",
    "ensure",
    "vast_open",
    "vast_view",
    "vast_status",
    "vast_goto",
    "vast_find",
    "vast_layout",
    "vast_read",
    "vast_export",
    "vast_filter",
    "vast_sort",
    "vast_build_index",
    "vast_attach_index",
    "vast_detach_index",
    "vast_is_running",
    "vast_log_path",
]
