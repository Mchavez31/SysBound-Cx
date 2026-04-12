"""
Compare two drawing PDFs and produce structured results + Excel export.
"""
from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Callable

from openpyxl import Workbook

ProgressCb = Callable[[int, str], None] | None
from openpyxl.styles import PatternFill

from services import pdf_parser


def _view_fields_for_tag(tag: dict[str, Any] | None, suffix: str) -> dict[str, Any]:
    """Tag hit box center + page size for focused PDF/snippet viewers (pdfplumber coordinates)."""
    if not tag:
        return {}
    out: dict[str, Any] = {}
    for src, dest in (
        ("x", f"tag_x_{suffix}"),
        ("y", f"tag_y_{suffix}"),
        ("page_width", f"page_width_{suffix}"),
        ("page_height", f"page_height_{suffix}"),
    ):
        v = tag.get(src)
        if v is None:
            continue
        try:
            out[dest] = float(v)
        except (TypeError, ValueError):
            pass
    return out


def _norm_hex(h: str | None) -> str | None:
    if not h:
        return None
    return h.strip().upper()


def _norm_sub(s: str | None) -> str | None:
    if s is None:
        return None
    t = str(s).strip()
    return t if t else None


def _action_for_row(
    change_type: str,
    is_x: bool,
    *,
    has_future: bool = False,
) -> str:
    if is_x:
        return "x_tag"
    if has_future:
        return "future"
    if change_type == "new":
        return "assign_subsystem"
    if change_type == "removed":
        return "review_removal"
    if change_type in ("subsystem_changed", "color_changed"):
        return "review_change"
    return "none"


def compare_systemized_vs_systemized(
    path_a: str,
    path_b: str,
    drawing_a_id: str,
    drawing_b_id: str,
    project_id: str,
    drawing_number_a: str,
    drawing_number_b: str,
    progress_cb: ProgressCb = None,
) -> dict[str, Any]:
    """
    Compare two systemized PDFs by subsystem assignment per tag (not raw tag equality).
    """
    if progress_cb:
        progress_cb(2, "Reading drawings (parallel)…")

    completion = {"a": 0.0, "b": 0.0}
    prog_lock = threading.Lock()

    def _wrap_progress(side: str, lo: int, hi: int):
        span = max(1, hi - lo)

        def inner(p: int, msg: str) -> None:
            clamped = min(max(int(p), lo), hi)
            frac = (clamped - lo) / span
            with prog_lock:
                completion[side] = max(completion[side], min(1.0, frac))
                overall = 3 + int(22 * (completion["a"] + completion["b"]) / 2)
                overall = min(27, max(3, overall))
                if progress_cb:
                    progress_cb(overall, msg)

        return inner

    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_a = pool.submit(
            pdf_parser.extract_all,
            path_a,
            progress_cb=_wrap_progress("a", 3, 17),
            progress_lo=3,
            progress_hi=17,
            progress_label="Drawing A",
        )
        fut_b = pool.submit(
            pdf_parser.extract_all,
            path_b,
            progress_cb=_wrap_progress("b", 19, 27),
            progress_lo=19,
            progress_hi=27,
            progress_label="Drawing B",
        )
        result_a = fut_a.result()
        result_b = fut_b.result()

    tags_a = {t["tag_number"]: t for t in result_a["tags"]}
    tags_b = {t["tag_number"]: t for t in result_b["tags"]}

    all_nums = set(tags_a.keys()) | set(tags_b.keys())
    only_a = set(tags_a.keys()) - set(tags_b.keys())
    only_b = set(tags_b.keys()) - set(tags_a.keys())
    both = set(tags_a.keys()) & set(tags_b.keys())

    rows: list[dict[str, Any]] = []
    unchanged_count = 0

    sorted_nums = sorted(all_nums)
    n_tag = len(sorted_nums)
    for i, tn in enumerate(sorted_nums):
        if progress_cb and n_tag > 0 and (i == 0 or i == n_tag - 1 or i % max(1, n_tag // 25) == 0):
            p = 28 + int(62 * i / max(n_tag, 1))
            progress_cb(min(90, p), f"Comparing tags ({i + 1}/{n_tag})…")
        in_a = tn in tags_a
        in_b = tn in tags_b
        ta = tags_a.get(tn)
        tb = tags_b.get(tn)

        if in_a and not in_b:
            is_x = bool(ta and ta.get("is_x_tag"))
            rows.append(
                {
                    "tag_number": tn,
                    "tag_type": (ta or {}).get("tag_type") or "other",
                    "change_type": "removed",
                    "action_needed": "review_removal",
                    "subsystem_a": _norm_sub((ta or {}).get("nearest_subsystem")),
                    "subsystem_b": None,
                    "color_a": _norm_hex((ta or {}).get("nearest_subsystem_color")),
                    "color_b": None,
                    "drawing_side": "A",
                    "page_a": (ta or {}).get("page_number"),
                    "page_b": None,
                    "is_x_tag": is_x,
                    "drawing_id_a": drawing_a_id,
                    "drawing_id_b": drawing_b_id,
                    "drawing_number_a": drawing_number_a or "",
                    "drawing_number_b": drawing_number_b or "",
                    **_view_fields_for_tag(ta, "a"),
                }
            )
            continue

        if in_b and not in_a:
            is_x = bool(tb and tb.get("is_x_tag"))
            rows.append(
                {
                    "tag_number": tn,
                    "tag_type": (tb or {}).get("tag_type") or "other",
                    "change_type": "new",
                    "action_needed": "x_tag" if is_x else "assign_subsystem",
                    "subsystem_a": None,
                    "subsystem_b": _norm_sub((tb or {}).get("nearest_subsystem")),
                    "color_a": None,
                    "color_b": _norm_hex((tb or {}).get("nearest_subsystem_color")),
                    "drawing_side": "B",
                    "page_a": None,
                    "page_b": (tb or {}).get("page_number"),
                    "is_x_tag": is_x,
                    "drawing_id_a": drawing_a_id,
                    "drawing_id_b": drawing_b_id,
                    "drawing_number_a": drawing_number_a or "",
                    "drawing_number_b": drawing_number_b or "",
                    **_view_fields_for_tag(tb, "b"),
                }
            )
            continue

        assert ta is not None and tb is not None
        sub_a = _norm_sub(ta.get("nearest_subsystem"))
        sub_b = _norm_sub(tb.get("nearest_subsystem"))
        col_a = _norm_hex(ta.get("nearest_subsystem_color"))
        col_b = _norm_hex(tb.get("nearest_subsystem_color"))
        is_x = bool(ta.get("is_x_tag") or tb.get("is_x_tag"))

        if sub_a != sub_b:
            ct = "subsystem_changed"
        elif col_a != col_b:
            ct = "color_changed"
        else:
            ct = "unchanged"

        if ct == "unchanged":
            unchanged_count += 1
            continue

        action = "review_change"

        rows.append(
            {
                "tag_number": tn,
                "tag_type": ta.get("tag_type") or tb.get("tag_type") or "other",
                "change_type": ct,
                "action_needed": action,
                "subsystem_a": sub_a,
                "subsystem_b": sub_b,
                "color_a": col_a,
                "color_b": col_b,
                "drawing_side": "both",
                "page_a": ta.get("page_number"),
                "page_b": tb.get("page_number"),
                "is_x_tag": is_x,
                "drawing_id_a": drawing_a_id,
                "drawing_id_b": drawing_b_id,
                "drawing_number_a": drawing_number_a or "",
                "drawing_number_b": drawing_number_b or "",
                **_view_fields_for_tag(ta, "a"),
                **_view_fields_for_tag(tb, "b"),
            }
        )

    if progress_cb:
        progress_cb(92, "Building summary…")

    subsystem_changed = sum(1 for r in rows if r["change_type"] == "subsystem_changed")
    color_changed = sum(1 for r in rows if r["change_type"] == "color_changed")

    summary = {
        "total_new": sum(1 for r in rows if r["change_type"] == "new"),
        "total_removed": sum(1 for r in rows if r["change_type"] == "removed"),
        "total_unchanged": unchanged_count,
        "total_subsystem_changes": subsystem_changed + color_changed,
        "subsystem_changed": subsystem_changed,
        "color_changed": color_changed,
        "total_tags_a": len(tags_a),
        "total_tags_b": len(tags_b),
        "total_x_tags": sum(1 for r in rows if r.get("is_x_tag")),
    }

    debug = {
        "drawing_a": pdf_parser.build_extraction_debug(result_a),
        "drawing_b": pdf_parser.build_extraction_debug(result_b),
        "labels_found_a": result_a.get("label_count", 0),
        "labels_found_b": result_b.get("label_count", 0),
        "subsystems_in_a": result_a.get("subsystems_found") or [],
        "subsystems_in_b": result_b.get("subsystems_found") or [],
    }

    return {
        "comparison_type": "systemized_vs_systemized",
        "drawing_a_id": drawing_a_id,
        "drawing_b_id": drawing_b_id,
        "project_id": project_id,
        "drawing_number_a": drawing_number_a,
        "drawing_number_b": drawing_number_b,
        "tags_only_in_a": sorted(only_a),
        "tags_only_in_b": sorted(only_b),
        "tags_in_both": sorted(both),
        "rows": rows,
        "summary": summary,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "debug": debug,
    }


def compare_drawings(
    drawing_a_path: str,
    drawing_b_path: str,
    role_a: str,
    role_b: str,
    comparison_type: str,
    drawing_a_id: str,
    drawing_b_id: str,
    project_id: str,
    drawing_number_a: str,
    drawing_number_b: str,
    progress_cb: ProgressCb = None,
) -> dict[str, Any]:
    if comparison_type == "systemized_vs_systemized":
        return compare_systemized_vs_systemized(
            drawing_a_path,
            drawing_b_path,
            drawing_a_id,
            drawing_b_id,
            project_id,
            drawing_number_a,
            drawing_number_b,
            progress_cb=progress_cb,
        )

    if progress_cb:
        progress_cb(5, "Extracting tags from drawing A…")
    tags_a = pdf_parser.extract_tags(drawing_a_path)
    if progress_cb:
        progress_cb(22, "Extracting tags from drawing B…")
    tags_b = pdf_parser.extract_tags(drawing_b_path)

    sys_a = role_a in ("current_systemized", "prior_systemized")
    sys_b = role_b in ("current_systemized", "prior_systemized")
    if sys_a:
        if progress_cb:
            progress_cb(38, "Resolving colors (drawing A)…")
        tags_a = pdf_parser.extract_colors_near_tags(drawing_a_path, tags_a)
    if sys_b:
        if progress_cb:
            progress_cb(55, "Resolving colors (drawing B)…")
        tags_b = pdf_parser.extract_colors_near_tags(drawing_b_path, tags_b)

    map_a = {t["tag_number"]: t for t in tags_a}
    map_b = {t["tag_number"]: t for t in tags_b}
    set_a, set_b = set(map_a.keys()), set(map_b.keys())

    only_a = set_a - set_b
    only_b = set_b - set_a
    both = set_a & set_b

    rows: list[dict[str, Any]] = []

    def add_row(
        tag_number: str,
        change_type: str,
        side: str,
        ta: dict | None,
        tb: dict | None,
    ) -> None:
        is_x = bool((ta or tb or {}).get("is_x_tag"))
        color_a = (ta or {}).get("color_hex")
        color_b = (tb or {}).get("color_hex")
        prev_sub = None
        action = _action_for_row(change_type, is_x)
        rows.append(
            {
                "tag_number": tag_number,
                "tag_type": (ta or tb or {}).get("tag_type") or "other",
                "change_type": change_type,
                "action_needed": action,
                "subsystem_a": prev_sub,
                "subsystem_b": prev_sub,
                "color_a": color_a,
                "color_b": color_b,
                "drawing_side": side,
                "page_a": (ta or {}).get("page_number"),
                "page_b": (tb or {}).get("page_number"),
                "is_x_tag": is_x,
                "drawing_id_a": drawing_a_id,
                "drawing_id_b": drawing_b_id,
                "drawing_number_a": drawing_number_a or "",
                "drawing_number_b": drawing_number_b or "",
                **_view_fields_for_tag(ta, "a"),
                **_view_fields_for_tag(tb, "b"),
            }
        )

    if progress_cb:
        progress_cb(72, "Building change rows…")

    for tn in sorted(only_a):
        add_row(tn, "removed", "A", map_a.get(tn), None)
    for tn in sorted(only_b):
        add_row(tn, "new", "B", None, map_b.get(tn))
    unchanged_both = 0
    for tn in sorted(both):
        ta, tb = map_a[tn], map_b[tn]
        ct = "unchanged"
        if comparison_type in ("new_vs_systemized", "new_vs_new"):
            ca, cb = _norm_hex(ta.get("color_hex")), _norm_hex(tb.get("color_hex"))
            if ca != cb:
                ct = "color_changed"
        if ct == "unchanged":
            unchanged_both += 1
            continue
        add_row(tn, ct, "both", ta, tb)

    summary = {
        "total_new": sum(1 for r in rows if r["change_type"] == "new"),
        "total_removed": sum(1 for r in rows if r["change_type"] == "removed"),
        "total_unchanged": unchanged_both,
        "total_subsystem_changes": sum(
            1 for r in rows if r["change_type"] in ("subsystem_changed", "color_changed")
        ),
        "total_x_tags": sum(1 for r in rows if r.get("is_x_tag")),
    }

    return {
        "comparison_type": comparison_type,
        "drawing_a_id": drawing_a_id,
        "drawing_b_id": drawing_b_id,
        "project_id": project_id,
        "drawing_number_a": drawing_number_a,
        "drawing_number_b": drawing_number_b,
        "tags_only_in_a": list(only_a),
        "tags_only_in_b": list(only_b),
        "tags_in_both": list(both),
        "rows": rows,
        "summary": summary,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "debug": {
            "drawing_a": {
                "total_tags_extracted": len(tags_a),
                "total_labels_extracted": 0,
                "subsystems_found": [],
                "sample_tags": [],
            },
            "drawing_b": {
                "total_tags_extracted": len(tags_b),
                "total_labels_extracted": 0,
                "subsystems_found": [],
                "sample_tags": [],
            },
        },
    }


def generate_excel_report(comparison_result: dict[str, Any], project_name: str) -> bytes:
    wb = Workbook()
    ws1 = wb.active
    ws1.title = "Summary"
    ws1["A1"] = "Project"
    ws1["B1"] = project_name
    ws1["A2"] = "Comparison type"
    ws1["B2"] = comparison_result.get("comparison_type", "")
    ws1["A3"] = "Date"
    ws1["B3"] = comparison_result.get("generated_at", "")
    s = comparison_result.get("summary") or {}
    ws1["A5"] = "New"
    ws1["B5"] = s.get("total_new", 0)
    ws1["A6"] = "Removed"
    ws1["B6"] = s.get("total_removed", 0)
    ws1["A7"] = "Unchanged (count only; not in sheets below)"
    ws1["B7"] = s.get("total_unchanged", 0)
    ws1["A8"] = "Subsystem/color changes"
    ws1["B8"] = s.get("total_subsystem_changes", 0)
    if "subsystem_changed" in s:
        ws1["A9"] = "Subsystem changed"
        ws1["B9"] = s.get("subsystem_changed", 0)
        ws1["A10"] = "Color changed"
        ws1["B10"] = s.get("color_changed", 0)

    fill_new = PatternFill("solid", fgColor="FFF3CD")
    fill_removed = PatternFill("solid", fgColor="F8D7DA")
    fill_changed = PatternFill("solid", fgColor="CCE5FF")

    ws2 = wb.create_sheet("All Tags")
    headers = [
        "Tag Number",
        "Tag Type",
        "Document (Drawing A)",
        "Document (Drawing B)",
        "Subsystem A",
        "Subsystem B",
        "Color A",
        "Color B",
        "Change Type",
        "Action Needed",
        "Page A",
        "Page B",
        "X-Tag",
    ]
    for c, h in enumerate(headers, 1):
        ws2.cell(row=1, column=c, value=h)
    dn_a = comparison_result.get("drawing_number_a", "")
    dn_b = comparison_result.get("drawing_number_b", "")
    ncols = len(headers)
    for i, row in enumerate(comparison_result.get("rows") or [], start=2):
        doc_a = row.get("drawing_number_a") or dn_a
        doc_b = row.get("drawing_number_b") or dn_b
        ws2.cell(row=i, column=1, value=row.get("tag_number"))
        ws2.cell(row=i, column=2, value=row.get("tag_type"))
        ws2.cell(row=i, column=3, value=doc_a)
        ws2.cell(row=i, column=4, value=doc_b)
        ws2.cell(row=i, column=5, value=row.get("subsystem_a"))
        ws2.cell(row=i, column=6, value=row.get("subsystem_b"))
        ws2.cell(row=i, column=7, value=row.get("color_a"))
        ws2.cell(row=i, column=8, value=row.get("color_b"))
        ws2.cell(row=i, column=9, value=row.get("change_type"))
        ws2.cell(row=i, column=10, value=row.get("action_needed"))
        ws2.cell(row=i, column=11, value=row.get("page_a"))
        ws2.cell(row=i, column=12, value=row.get("page_b"))
        ws2.cell(row=i, column=13, value="Y" if row.get("is_x_tag") else "")
        ct = row.get("change_type")
        fl = None
        if ct == "new":
            fl = fill_new
        elif ct == "removed":
            fl = fill_removed
        elif ct in ("subsystem_changed", "color_changed"):
            fl = fill_changed
        if fl:
            for col in range(1, ncols + 1):
                ws2.cell(row=i, column=col).fill = fl

    ws3 = wb.create_sheet("Action Required")
    ws3.append(headers)
    for row in comparison_result.get("rows") or []:
        if row.get("action_needed") in (None, "none"):
            continue
        doc_a = row.get("drawing_number_a") or dn_a
        doc_b = row.get("drawing_number_b") or dn_b
        ws3.append(
            [
                row.get("tag_number"),
                row.get("tag_type"),
                doc_a,
                doc_b,
                row.get("subsystem_a"),
                row.get("subsystem_b"),
                row.get("color_a"),
                row.get("color_b"),
                row.get("change_type"),
                row.get("action_needed"),
                row.get("page_a"),
                row.get("page_b"),
                "Y" if row.get("is_x_tag") else "",
            ]
        )

    bio = BytesIO()
    wb.save(bio)
    return bio.getvalue()


def result_to_json_text(result: dict[str, Any]) -> str:
    return json.dumps(result, default=str)
