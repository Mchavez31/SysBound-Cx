"""
PDF extraction for drawing metadata, tags, and subsystem labels (pdfplumber).
"""
from __future__ import annotations

import logging
import math
import os
import re
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Optional

import pdfplumber

# Willow Tagging Specification (WILG-WFXX-ADM-SPC-WOD-…): hyphenated tag numeric block lengths.
# §6.0 AAA-NNNNN (5-digit sequence); §6.2 manual valves AA-NNNNNNN (7); §6.3 / §6.9 line & instrument IDs (7);
# occasional 6-digit cases (e.g. SP-specialty §6.5). Parsed together as one contiguous digit run: 5–7 digits.
WILLOW_NUMERIC_SEGMENT_MIN_LEN = 5
WILLOW_NUMERIC_SEGMENT_MAX_LEN = 7
_WIL_DIG = f"{{{WILLOW_NUMERIC_SEGMENT_MIN_LEN},{WILLOW_NUMERIC_SEGMENT_MAX_LEN}}}"

# Primary: cap digit run and suffix length to avoid merged / garbage strings from wide word windows
TAG_RE_PRIMARY = re.compile(rf"\b[A-Z]{{1,5}}-[0-9]{_WIL_DIG}[A-Z0-9]{{0,4}}\b")
TAG_RE_X = re.compile(r"\b[A-Z]{1,5}-[0-9A-Z]{0,6}X{2,}[0-9A-Z]{0,6}\b")
# Space between prefix and digits (common on systemized P&IDs)
TAG_RE_SPACE = re.compile(rf"\b([A-Z]{{1,5}})\s+([0-9]{_WIL_DIG}[A-Z0-9]{{0,4}})\b")
# Space-separated with intervening noise (e.g., "ZIO U U 9881715" where U are status indicators)
TAG_RE_SPACE_WITH_NOISE = re.compile(rf"\b([A-Z]{{1,5}})(?:\s+[A-Z]{{1,2}})*\s+([0-9]{_WIL_DIG}[A-Z0-9]{{0,4}})\b")
# Joined without separator — only safe on short windows (applied with extra guards)
TAG_RE_JOINED = re.compile(rf"\b([A-Z]{{2,5}})([0-9]{_WIL_DIG}[A-Z0-9]{{0,4}})\b")
# Piping / instrument line designation: 2"-AI-9881719-A1V3X (inch + instrument + digit block + sheet/suffix)
# Suffix: simple alphanumeric OR alphanumeric followed by fraction pattern like -1/2"-HE-SC
# Use negative lookahead to stop before a new tag pattern (LETTER-DIGITS) but allow single letters
TAG_RE_PIPELINE = re.compile(
    rf'(\d{{1,2}})"\s*-\s*([A-Za-z]{{1,5}})\s*-\s*(\d{_WIL_DIG})\s*-\s*([A-Za-z0-9]+(?:-\d+(?:/\d+)?"-[A-Z]{{2,6}})?(?![A-Z]{{2,}}-\d{{5}}))',
    re.I,
)
TAG_RE_PIPELINE_COMPACT = re.compile(
    rf'(\d{{1,2}})"-([A-Za-z]{{1,5}})-(\d{_WIL_DIG})-([A-Za-z0-9]+(?:-\d+(?:/\d+)?"-[A-Z]{{2,6}})?(?![A-Z]{{2,}}-\d{{5}}))',
    re.I,
)
# PDF sometimes drops the quote glyph; require 1–2 digit size + full line structure
TAG_RE_PIPELINE_NOQUOTE = re.compile(
    rf"\b(\d{{1,2}})-([A-Za-z]{{1,5}})-(\d{_WIL_DIG})-([A-Za-z0-9]+(?:-\d+(?:/\d+)?-[A-Z]{{2,6}})?(?![A-Z]{{2,}}-\d{{5}}))\b",
    re.I,
)
# Line number without leading size (suffix must look like discipline code, not short rev)
TAG_RE_LINE_NO_SIZE = re.compile(
    rf"\b([A-Za-z]{{1,5}})-(\d{_WIL_DIG})-([A-Za-z0-9]+(?:-\d+(?:/\d+)?-[A-Z]{{2,6}})?(?![A-Z]{{2,}}-\d{{5}}))\b",
    re.I,
)
# pdfplumber may insert spaces around hyphens inside a word-run
TAG_RE_PIPELINE_SPACED = re.compile(
    rf'(\d{{1,2}})"\s+-\s+([A-Za-z]{{1,5}})\s+-\s+(\d{_WIL_DIG})\s+-\s+([A-Za-z0-9]+(?:-\d+(?:/\d+)?"-[A-Z]{{2,6}})?(?![A-Z]{{2,}}-\d{{5}}))',
    re.I,
)

SUBSYSTEM_LABEL_TEXT_RE = re.compile(r"\b(\d{2}-\d{2})\b")

# Drawing number pattern (long dashed codes)
DRAWING_NUM_RE = re.compile(
    r"\b([A-Z]{3,5}-[A-Z0-9]{2,5}-[A-Z]{3}-[A-Z]{3,4}-[A-Z]{3}-[0-9]{5}-[A-Z0-9]{2,}-[0-9]{2,})\b",
    re.IGNORECASE,
)

PLANT_PREFIX_MAP = [
    (re.compile(r"WILG", re.I), "WCF"),
    (re.compile(r"WWOC", re.I), "WOC"),
    (re.compile(r"BT10", re.I), "BT1"),
    (re.compile(r"BT20", re.I), "BT2"),
    (re.compile(r"BT30", re.I), "BT3"),
    (re.compile(r"WKPD", re.I), "KPAD"),
]

def _env_workers(name: str, default: int, lo: int, hi: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return max(lo, min(hi, default))
    try:
        return max(lo, min(hi, int(raw)))
    except ValueError:
        return max(lo, min(hi, default))


# Parallel page chunks (each chunk opens the PDF once). Default 8; cap to limit RAM with huge PDFs.
_w = _env_workers("PDF_EXTRACT_WORKERS", 8, 2, 16)
_MAX_TAG_WORKERS = _w
_MAX_LABEL_WORKERS = _w
_MAX_COMBINED_WORKERS = _w

# Avoid TAG_RE_JOINED false positives on common English / title words
_SKIP_JOINED_PREFIX = {
    "THE", "AND", "FOR", "NOT", "ARE", "ALL", "CAN", "HAS", "SHE", "BUT", "OUT", "USE",
    "MAY", "ONE", "TWO", "THAT", "THIS", "WITH", "FROM", "WAS", "WERE", "BEEN", "HAVE",
    "WILL", "EACH", "WHICH", "THEIR", "SAFETY", "NOTE", "REFER", "DRAWING", "SCALE",
    "SHEET", "REV", "DATE", "PROJECT", "SYSTEM", "AREA", "ZONE", "LINE", "SIZE",
    "CONT",
    "CONTI",
    "MODULE",
    "NOTES",
    "GENERAL",
    "DETAIL",
    "DETAILS",
    "NORTH",
    "SOUTH",
    "EAST",
    "WEST",
    "LIMIT",
    "RE",
}
# Pseudo-tags from prose / scenarios (CASE: FIRE) or WGXX drawing references — not equipment tags.
_BAD_TAG_PREFIXES = frozenset(
    {
        "FIRE",
        "FIRES",
        "IRES",
        "RES",
        "ES",
        "CASE",
        "NOTE",
        "NOTES",
        "FROM",
        "GXX",
        "WGXX",
        "WFXX",
        # RE-95800… glued from notes (“REFER”, “REMOTE”, prose) — not instrument RE-
        "RE",
        "AREA",
        "SHEETS",
        "DFCS",
        "FCCS",
        "MCC",
        "VM",  # Not in tagging spec (pages 23-26)
    }
)


def normalize_pipeline_display(inch_part: str, prefix: str, digits: str, suffix: str) -> str:
    """Canonical piping line tag, e.g. 2"-AI-9881719-A1V3X (ASCII double-quote for inch mark)."""
    # Strip leading zeros from inch part (02" -> 2")
    inch_clean = str(inch_part).strip().lstrip('0') or '0'
    return f'{inch_clean}"-{prefix.upper()}-{digits}-{suffix.upper()}'


def _line_suffix_looks_instr_line(suf: str) -> bool:
    """Require mixed alnum suffix (sheet / line discipline), not bare rev like '-01'."""
    su = (suf or "").upper()
    if len(su) < 4:
        return False
    return bool(re.search(r"[A-Z]", su)) and bool(re.search(r"[0-9]", su))


def is_plausible_pipeline_line_tag(tn: str) -> bool:
    norm = normalize_tag_number(tn).upper()
    if len(norm) < 10 or len(norm) > 48:
        return False
    parts = norm.split("-")
    if len(parts) < 3:
        return False
    head = parts[0].replace('"', "").strip()

    # 2"-AI-9881719-A1V3X → parts [2"", AI, 9881719, …] after normalize may keep quote on segment
    if head.isdigit() and 1 <= len(head) <= 2 and head != "0" and len(parts) >= 4:
        pref, mid = parts[1], parts[2]
        suf_rest = "-".join(parts[3:])
        
        # Check for concatenated tag at the end (e.g., ends with "092"-AI")
        # Pattern: ...suffix-DIGITS"-PREFIX or ...suffix DIGITS"-PREFIX
        concat_pattern = re.search(r'(\d{1,2})["\']?\s*-?\s*([A-Z]{1,5})$', suf_rest)
        if concat_pattern:
            # This looks like another tag got concatenated, reject it
            return False
        
        if (
            pref in _BAD_TAG_PREFIXES
            or not pref.isalpha()
            or not (
                WILLOW_NUMERIC_SEGMENT_MIN_LEN <= len(mid) <= WILLOW_NUMERIC_SEGMENT_MAX_LEN
            )
            or not mid.isdigit()
        ):
            return False
        
        # Check for repeated digit blocks in the suffix (e.g., A1V3X9881510 where 9881510 is a tag number)
        digit_run_in_suf = re.search(rf'\d{{{WILLOW_NUMERIC_SEGMENT_MIN_LEN},{WILLOW_NUMERIC_SEGMENT_MAX_LEN}}}', suf_rest)
        if digit_run_in_suf:
            # Suffix contains a 5-7 digit run, likely a concatenated tag number
            return False
            
        return _line_suffix_looks_instr_line(suf_rest)

    # AI-9881719-A1V3X — no nominal size extracted (line number numeric block §6.3 / §6.9)
    if len(parts) == 3:
        pref, mid, suf = parts[0], parts[1], parts[2]
        if (
            pref in _BAD_TAG_PREFIXES
            or not pref.isalpha()
            or not (1 <= len(pref) <= 5)
            or not (WILLOW_NUMERIC_SEGMENT_MIN_LEN <= len(mid) <= WILLOW_NUMERIC_SEGMENT_MAX_LEN)
            or not mid.isdigit()
        ):
            return False
        
        # Check for repeated digit blocks in suffix
        digit_run_in_suf = re.search(rf'\d{{{WILLOW_NUMERIC_SEGMENT_MIN_LEN},{WILLOW_NUMERIC_SEGMENT_MAX_LEN}}}', suf)
        if digit_run_in_suf:
            return False
            
        return _line_suffix_looks_instr_line(suf)

    return False


def _bogus_I_split_from_ai_line(chunk: str, tn: str) -> bool:
    """
    Word windows can drop leading 'A' so we match I-9881719 inside 2"-AI-9881719-A1V3X text.
    """
    n = normalize_tag_number(tn)
    mi = re.match(
        rf"^I-(\d{{{WILLOW_NUMERIC_SEGMENT_MIN_LEN},{WILLOW_NUMERIC_SEGMENT_MAX_LEN}}})$",
        n,
    )
    if not mi:
        return False
    digits = mi.group(1)
    c = chunk.upper()
    return bool(re.search(rf'(?:\d{{1,2}}"\s*-\s*)?AI-{re.escape(digits)}\b', c))


def _primary_acronym_for_filter(tn: str) -> str:
    """Leading instrument/drawing acronym for blocklist checks (handles 2"-AI-… piping lines)."""
    n = normalize_tag_number(tn)
    if '"' in n:
        after = n.split("-", 1)
        if len(after) < 2:
            return ""
        tail = after[1]
        seg = tail.split("-")[0]
        return seg.upper() if seg.isalpha() else ""
    if "-" not in n:
        return ""
    return n.split("-")[0].upper()


def _hyphen_compact_tag_truncated_in_source(source: str, m: re.Match) -> bool:
    """
    DROP PREFIX-hyphen-digitBlock matches when digit run breaks across pdfplumber tokens
    (e.g. AI-98817 glued before 19-A1V…) or when the same substring is the short form of an
    instrument line ending in '-A1V3X'-style suffix in one window.
    """
    end = m.end()
    if end >= len(source):
        return False
    rest = source[end:]
    if rest[:1].isdigit():
        return True
    if re.match(r"^[ \t]{1,4}\d", rest):
        return True
    trimmed = rest.lstrip(" \t")
    hm = re.match(r"^-([A-Z0-9]{2}[A-Z0-9\-]{1,26})", trimmed, re.I)
    if hm:
        first_seg = hm.group(1).split("-")[0].upper()
        if first_seg.isdigit():
            return False
        return _line_suffix_looks_instr_line(first_seg)
    return False


def _refine_truncated_hyphen_duplicates(tags: dict[str, dict[str, Any]]) -> None:
    """
    If PREFIX-digitsSHORT exists but PREFIX-digitsLONG-suffixFull also exists where digitsSHORT is a proper
    prefix of digitsLONG, keep only the fuller tag (drops split OCR fragments like AI-98817 vs AI-9881719-A1…).
    Also handles pipeline tag suffix variations (A1V3 vs A1V3X vs A1V3X1).
    """
    twos: list[tuple[str, str, str]] = []
    triples: list[tuple[str, str, str, str]] = []
    pipelines: list[tuple[str, str, str, str, str]] = []  # key, inch, prefix, digits, suffix
    
    for k in tags.keys():
        n = canonical_simple_extracted_tag(k).upper()
        
        # Pipeline tags with inch prefix
        if '"' in n:
            parts = [p for p in n.split("-") if p]
            if len(parts) >= 4:
                inch_part = parts[0].replace('"', '').strip()
                if inch_part.isdigit() and 1 <= len(inch_part) <= 2:
                    pref, digs = parts[1], parts[2]
                    suf = "-".join(parts[3:])
                    if (pref.isalpha() and 
                        WILLOW_NUMERIC_SEGMENT_MIN_LEN <= len(digs) <= WILLOW_NUMERIC_SEGMENT_MAX_LEN and 
                        digs.isdigit()):
                        pipelines.append((k, inch_part, pref.upper(), digs, suf.upper()))
            continue
            
        parts = [p for p in n.split("-") if p]
        if len(parts) == 2:
            pref, digs = parts[0], parts[1]
            if not pref.isalpha() or not (1 <= len(pref) <= 5):
                continue
            if not (WILLOW_NUMERIC_SEGMENT_MIN_LEN <= len(digs) <= WILLOW_NUMERIC_SEGMENT_MAX_LEN) or not digs.isdigit():
                continue
            twos.append((k, pref.upper(), digs))
        elif len(parts) == 3:
            pref, digs, suf = parts[0], parts[1], parts[2]
            if pref in _BAD_TAG_PREFIXES or not pref.isalpha() or len(pref) > 5:
                continue
            if not (WILLOW_NUMERIC_SEGMENT_MIN_LEN <= len(digs) <= WILLOW_NUMERIC_SEGMENT_MAX_LEN) or not digs.isdigit():
                continue
            if not _line_suffix_looks_instr_line(suf):
                continue
            triples.append((k, pref.upper(), digs, suf.upper()))

    # Drop simple tags when fuller ones exist
    drop_short: list[str] = []
    for k_short, pref_s, digs_s in twos:
        for _k_long, pref_l, digs_l, _suf_l in triples:
            if pref_s != pref_l:
                continue
            if digs_s == digs_l:
                drop_short.append(k_short)
                break
            if len(digs_s) >= len(digs_l):
                continue
            if digs_l.startswith(digs_s):
                drop_short.append(k_short)
                break
    
    # Handle pipeline tag suffix variations - keep longest suffix
    pipeline_groups: dict[tuple[str, str, str], list[tuple[str, str]]] = {}  # (inch, prefix, digits) -> [(key, suffix)]
    for k, inch, pref, digs, suf in pipelines:
        key_tuple = (inch, pref, digs)
        if key_tuple not in pipeline_groups:
            pipeline_groups[key_tuple] = []
        pipeline_groups[key_tuple].append((k, suf))
    
    for group_key, tag_list in pipeline_groups.items():
        if len(tag_list) <= 1:
            continue
        # Sort by suffix length descending, then alphabetically
        tag_list.sort(key=lambda x: (-len(x[1]), x[1]))
        best_suf = tag_list[0][1]
        # Drop tags with suffixes that are prefixes of the best one, or very similar
        for k, suf in tag_list[1:]:
            if (best_suf.startswith(suf) or  # A1V3X starts with A1V3
                suf.startswith(best_suf) or  # A1V3X1 starts with A1V3X
                len(best_suf) - len(suf) <= 2):  # Very similar length
                drop_short.append(k)
    
    for dk in dict.fromkeys(drop_short):
        tags.pop(dk, None)


def _refine_pipeline_conflicts(tags: dict[str, dict[str, Any]]) -> None:
    """
    If we keep a full piping line (2"-AI-9881719-…), drop shorter instrument-only keys for the same or truncated digit block.
    """
    pipeline_rows: list[tuple[str, str, str]] = []
    for k in tags:
        ku = k.upper()
        if '"' not in ku:
            continue
        m = re.match(
            rf'^\d{{1,2}}"-([A-Z]{{1,5}})-(\d{{{WILLOW_NUMERIC_SEGMENT_MIN_LEN},{WILLOW_NUMERIC_SEGMENT_MAX_LEN}}})-',
            ku,
        )
        if not m:
            continue
        pipeline_rows.append((k, m.group(1), m.group(2)))

    if not pipeline_rows:
        return

    for _pk, prefix, digits in pipeline_rows:
        drop_keys: list[str] = []
        for k in list(tags.keys()):
            ku = k.upper()
            if '"' in ku:
                continue
            sm = re.match(
                rf"^([A-Z]{{1,5}})-(\d{{{WILLOW_NUMERIC_SEGMENT_MIN_LEN},{WILLOW_NUMERIC_SEGMENT_MAX_LEN}}})(?:-[A-Z0-9]+)?$",
                ku,
            )
            if not sm:
                continue
            short_digits = sm.group(2)
            short_pref = sm.group(1)
            # Drop if prefix matches and digits are exact match OR truncated prefix
            prefix_match = short_pref == prefix or (short_pref == "I" and prefix == "AI")
            digits_match = (short_digits == digits or 
                           digits.startswith(short_digits) or 
                           short_digits.startswith(digits))
            if prefix_match and digits_match:
                drop_keys.append(k)
        for dk in drop_keys:
            tags.pop(dk, None)


def _infer_plant_from_drawing_number(dn: str) -> str | None:
    if not dn:
        return None
    u = dn.upper()
    for rx, plant in PLANT_PREFIX_MAP:
        if rx.search(u):
            return plant
    return None


def _infer_drawing_type(text: str) -> str | None:
    t = text.upper()
    if "PIPING AND INSTRUMENTATION" in t or "P&ID" in t or "P&ID" in text:
        return "P&ID"
    if "ONE LINE" in t or "SINGLE LINE" in t or "ONE-LINE" in t:
        return "SLD"
    if "PROCESS FLOW" in t or re.search(r"\bPFD\b", t):
        return "PFD"
    if "PANEL SCHEDULE" in t:
        return "Panel Schedule"
    if ("CABLE BLOCK" in t or "BLOCK DIAGRAM" in t) and "INSTRUMENT" in t:
        return "Automation"
    if "NETWORK" in t or "TELECOM" in t or "ARCHITECTURE" in t:
        return "Telecom"
    return None


def _extract_revision(text: str) -> str | None:
    m = re.search(r"\bREV\.?\s*([0-9]{1,2})\b", text, re.I)
    if m:
        return m.group(1)
    m = re.search(r"\bREVISION\s*([0-9]{1,2})\b", text, re.I)
    if m:
        return m.group(1)
    return None


def normalize_tag_number(raw: str) -> str:
    """Canonical form PREFIX-DIGITS for dedupe and comparison."""
    t = re.sub(r"\s+", "-", raw.strip().upper())
    while "--" in t:
        t = t.replace("--", "-")
    # Strip leading zeros from inch prefix in pipeline tags (02"-AI -> 2"-AI)
    t = re.sub(r'^0+(\d")', r'\1', t)
    return t


_NOTE_GLUED_ALPHA_TAIL = re.compile(
    # Notes glue the following prose word onto the numeric block (PI-9580090HIGH, …LOW …AIR).
    rf"^([A-Z]{{1,5}}-\d{_WIL_DIG})([A-Z]{{3,}})$"
)

# Match NOTE/NOTES with optional numbers (NOTE, NOTE2, NOTES, etc.)
_NOTE_SUFFIX_RE = re.compile(r"NOTE[S]?\d*$", re.I)

def canonical_simple_extracted_tag(tn: str) -> str:
    """Strip note/prose glued after PREFIX-Digits (excluding piping lines)."""
    n = normalize_tag_number(tn)
    if '"' in n:
        return n
    if is_plausible_pipeline_line_tag(n):
        return n
    
    # Strip NOTE/NOTES suffixes (including NOTE2, NOTES3, etc.)
    parts = n.split("-")
    if len(parts) >= 3:
        last_part = parts[-1].upper()
        if _NOTE_SUFFIX_RE.match(last_part):
            # Remove the NOTE suffix part
            n = "-".join(parts[:-1])
            return n
    
    # Original logic for pure alpha tails
    while True:
        m = _NOTE_GLUED_ALPHA_TAIL.match(n.upper())
        if not m:
            break
        tail = m.group(2)
        if tail.isalpha():
            n = m.group(1)
            continue
        break
    return n


def _is_plant_xx_sheet_continuation_reference(tn: str) -> bool:
    """
    Continued-on-drawing refs like WGXX-95004-01 or WFXX-65003-01 (plant/site + XX …).
    Not equipment tags — different plants use different prefixes before XX.
    """
    n = canonical_simple_extracted_tag(tn).upper()
    if '"' in n:
        return False
    parts = n.split("-")
    if len(parts) < 3:
        return False
    root = parts[0]
    if len(root) < 4 or not root.endswith("XX"):
        return False
    body = root[:-2]
    if not body.isalpha() or len(body) < 1:
        return False
    middle, last = parts[1], parts[-1]
    if not middle.isdigit() or not last.isdigit():
        return False
    if not 4 <= len(middle) <= 8:
        return False
    if not 2 <= len(last) <= 3:
        return False
    return True


_DETAIL_REF_RE = re.compile(
    # Detail / typical drawing callout (XV-10, MV-07, HV-7) — not a P&ID tag number block.
    r"^[A-Z]{2,5}-\d{1,3}$",
)


def _is_detail_drawing_sheet_reference(tn: str) -> bool:
    """Detail callout hyphen small sheet no. (XV-10, MOV-07, HV-7), not a tag number."""
    n = canonical_simple_extracted_tag(tn).upper()
    if '"' in n or n.count("-") != 1:
        return False
    return bool(_DETAIL_REF_RE.match(n))


def _is_drawing_number_in_titleblock(tn: str) -> bool:
    """
    Drawing/sheet numbers like U-6000859, P-1234567 (single/double letter + long digit string).
    These appear in title blocks, not equipment tags which have more structure.
    """
    n = canonical_simple_extracted_tag(tn).upper()
    if '"' in n:
        return False
    parts = n.split("-")
    if len(parts) != 2:
        return False
    prefix, suffix = parts[0], parts[1]
    # Single or double letter prefix
    if not (1 <= len(prefix) <= 2 and prefix.isalpha()):
        return False
    # Long digit sequence (6+ digits) with no letters = likely drawing number
    if len(suffix) >= 6 and suffix.isdigit():
        return True
    return False


def _has_revision_placeholder(tn: str) -> bool:
    """
    Tags with 4+ consecutive X's (XXXX) are revision placeholders, not actual tags.
    E.g., WD-5781714-XXXX37, TAG-XXXX, etc.
    """
    return "XXXX" in tn.upper()


def _is_module_banner_fake_tag(tn: str) -> bool:
    """
    Lines like WGJ4-MODULE LIMITS … — module code hyphen MODULE/CONT/LIMIT/etc., not tags.
    """
    n = normalize_tag_number(tn).upper()
    parts = [p for p in n.split("-") if p]
    if len(parts) < 2:
        return False
    head = parts[0]
    tail = parts[1]
    if len(head) < 3:
        return False
    letters = "".join(c for c in head if c.isalpha())
    if not letters.isalpha() or len(letters) < 2:
        return False
    if not re.search(r"[0-9]", head):
        return False
    banner_prefixes = ("MODULE", "LIMITS", "LIMIT", "CONTI", "CONT")
    tail_key = "".join(ch for ch in tail if ch.isalpha())
    return bool(tail_key) and any(tail_key == p or tail_key.startswith(p) for p in banner_prefixes)


def is_plausible_tag_number(tn: str) -> bool:
    """
    Reject merged OCR-style garbage: long digit runs, repeated acronyms (MV-9580056MV),
    doubled number blocks (95800289580028), long alpha tails (DRAINHEADER), NOTE suffixes.

    Hyphen numeric block lengths follow Willow spec §6.x (5-digit equipment AAA-NNNNN through
    7-digit valves / instruments AA-NNNNNNN — see constants WILLOW_NUMERIC_SEGMENT_*).
    """
    n = normalize_tag_number(tn)
    if len(n) < 5 or len(n) > 20:
        return False
    if re.search(r"X{2,}", n):
        return bool(re.match(r"^[A-Z]{1,5}-[0-9A-Z]{2,14}$", n)) and len(n) <= 18
    m = re.match(rf"^([A-Z]{{1,5}})-(\d{_WIL_DIG})([A-Z0-9]*)$", n)
    if not m:
        return False
    pref, nums, suff = m.group(1), m.group(2), (m.group(3) or "").upper()
    
    # Check for NOTE/NOTES suffixes (should have been stripped by canonical_simple_extracted_tag)
    if _NOTE_SUFFIX_RE.search(suff):
        return False
    
    # Prose glued to digits after hyphen: HIGH, STOP, AREA (HIGH needs len 4 alpha)
    if len(suff) >= 4 and suff.isalpha():
        return False
    # Repeated digit block (e.g. 95800289580028)
    for L in range(4, min(len(nums) // 2 + 1, 9)):
        if nums[:L] == nums[L : L * 2]:
            return False
    # Suffix repeats tag prefix (MV-9580056MV)
    if suff == pref:
        return False
    # Long word-like suffix glued to tag (U-57850DRAINHEADER)
    if len(suff) >= 5 and suff.isalpha():
        return False
    if len(suff) > 4:
        return False
    # Same acronym appears twice (…DFCS…DFCS)
    rest = n[len(pref) + 1 :]
    if pref in rest:
        return False
    # Single-letter suffix that's a common equipment prefix (likely concatenated from next tag)
    # E.g., V-98815S where S is from the next tag S-98840
    if len(suff) == 1 and suff in {"S", "V", "P", "T", "C", "E", "U", "X", "A", "M", "K", "L", "H"}:
        # Only if the digit part looks complete (ends naturally, not truncated)
        if len(nums) >= 5:  # Standard tag has complete 5-7 digit sequence
            return False
    return True


def classify_tag_category(tag_number: str) -> str:
    if is_plausible_pipeline_line_tag(tag_number):
        return "line"
    norm = normalize_tag_number(tag_number)
    prefix = norm.split("-")[0].upper() if "-" in norm else norm[:3].upper()
    valve_prefixes = {"MV", "XV", "SDV", "HV", "LV", "FV", "PV", "TV", "CV", "BDV", "PCV"}
    inst_prefixes = {
        "FI", "FIT", "PI", "PIT", "TI", "TIT", "LI", "LIT", "AI", "AIC", "PDI", "FIC", "PIC",
        "ZIO", "ZIC", "ZSC", "ZSO", "HS", "PT", "PDT", "ZS", "ZSH",
    }
    equip_prefixes = {"P", "T", "V", "S", "E", "C", "U", "X", "A", "M", "K"}
    if prefix in valve_prefixes:
        return "valve"
    if prefix in inst_prefixes:
        return "instrument"
    if len(prefix) <= 2 and prefix in equip_prefixes:
        return "equipment"
    if re.match(r"^[A-Z]{2,4}$", prefix) and len(tag_number) > 6:
        return "line"
    return "other"


def _norm_rgb_component(v: float) -> float:
    return v / 255.0 if v > 1.0 else v


def _hex_from_rgb_fill(r: float, g: float, b: float) -> str:
    r, g, b = _norm_rgb_component(r), _norm_rgb_component(g), _norm_rgb_component(b)

    def _byte(x: float) -> int:
        return max(0, min(255, int(round(x * 255)) if x <= 1 else int(round(x))))

    return f"#{_byte(r):02X}{_byte(g):02X}{_byte(b):02X}"


def _hex_from_rgb(r: float, g: float, b: float) -> str:
    def _c(x: float) -> int:
        return max(0, min(255, int(round(x * 255)) if x <= 1 else int(round(x))))

    if r <= 1 and g <= 1 and b <= 1:
        return f"#{_c(r):02x}{_c(g):02x}{_c(b):02x}"
    return f"#{int(r):02x}{int(g):02x}{int(b):02x}"


def _hex_to_rgb_ints(h: str | None) -> tuple[int, int, int] | None:
    """Parse #RRGGBB (any case) to 0–255 RGB."""
    if not h or not isinstance(h, str):
        return None
    s = h.strip().lstrip("#")
    if len(s) != 6:
        return None
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        return None


def _color_distance_hex(h1: str | None, h2: str | None) -> float:
    """Euclidean distance in RGB 0–255; large value if either color missing."""
    a = _hex_to_rgb_ints(h1)
    b = _hex_to_rgb_ints(h2)
    if not a or not b:
        return 1e9
    return math.sqrt(float((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2))


def _chunk_ranges(n: int, workers: int) -> list[tuple[int, int]]:
    if n <= 0:
        return []
    workers = max(1, min(workers, n))
    size = (n + workers - 1) // workers
    return [(i, min(i + size, n)) for i in range(0, n, size)]


def _flatten_chars(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def _tag_in_window(tn: str, chunk: str, chunk_spaced: str) -> bool:
    """Whether tag tn is supported by this word window (hyphen or space forms)."""
    flat = _flatten_chars(tn)
    if flat and (flat in _flatten_chars(chunk) or flat in _flatten_chars(chunk_spaced)):
        return True
    return tn in chunk or tn in chunk.replace(" ", "") or tn.replace("-", " ") in chunk_spaced


def _bbox_for_chunk_span(
    sub: list[dict[str, Any]], chunk: str, c0: int, c1: int
) -> tuple[float, float, float, float]:
    """Map character span [c0, c1) in chunk (concatenated word texts, no separators) to bbox."""
    pos = 0
    covering: list[dict[str, Any]] = []
    for w in sub:
        t = w.get("text", "") or ""
        wl = len(t)
        ws, we = pos, pos + wl
        # Only include words that significantly overlap with the matched span
        overlap = min(we, c1) - max(ws, c0)
        if overlap > 0:
            covering.append(w)
        pos += wl
    # If we didn't find any words, try to find the closest words to the span
    if not covering:
        # Find words closest to the matched character range
        best_words = []
        min_dist = float('inf')
        pos = 0
        for w in sub:
            t = w.get("text", "") or ""
            wl = len(t)
            ws, we = pos, pos + wl
            # Distance from word to span
            dist = max(0, max(c0 - we, ws - c1))
            if dist < min_dist:
                min_dist = dist
                best_words = [w]
            elif dist == min_dist:
                best_words.append(w)
            pos += wl
        covering = best_words[:3] if best_words else sub[:1]  # Limit to 3 closest words max
    x0 = min(float(w["x0"]) for w in covering)
    x1 = max(float(w["x1"]) for w in covering)
    top = min(float(w["top"]) for w in covering)
    bottom = max(float(w["bottom"]) for w in covering)
    return x0, x1, top, bottom


def _bbox_for_chunk_spaced_span(
    sub: list[dict[str, Any]], chunk_spaced: str, c0: int, c1: int
) -> tuple[float, float, float, float]:
    """Map character span in chunk_spaced (= ' '.join(word texts)) to bbox."""
    pos = 0
    covering: list[dict[str, Any]] = []
    for idx, w in enumerate(sub):
        if idx > 0:
            pos += 1  # single space between words
        t = w.get("text", "") or ""
        ws, we = pos, pos + len(t)
        # Only include words that significantly overlap with the matched span
        overlap = min(we, c1) - max(ws, c0)
        if overlap > 0:
            covering.append(w)
        pos = we
    # If we didn't find any words, find the closest ones
    if not covering:
        best_words = []
        min_dist = float('inf')
        pos = 0
        for idx, w in enumerate(sub):
            if idx > 0:
                pos += 1
            t = w.get("text", "") or ""
            ws, we = pos, pos + len(t)
            dist = max(0, max(c0 - we, ws - c1))
            if dist < min_dist:
                min_dist = dist
                best_words = [w]
            elif dist == min_dist:
                best_words.append(w)
            pos = we
        covering = best_words[:3] if best_words else sub[:1]  # Limit to 3 closest words max
    x0 = min(float(w["x0"]) for w in covering)
    x1 = max(float(w["x1"]) for w in covering)
    top = min(float(w["top"]) for w in covering)
    bottom = max(float(w["bottom"]) for w in covering)
    return x0, x1, top, bottom


def _has_reasonable_text_size(words: list[dict[str, Any]], min_size: float = 6.0) -> bool:
    """Check if words have reasonable font size (not tiny text like footnotes/metadata)."""
    if not words:
        return False
    # Check if any word has a reasonable size
    for w in words:
        height = w.get("height", 0) or w.get("bottom", 0) - w.get("top", 0)
        if height >= min_size:
            return True
    return False


def _extract_vertical_stacked_tags(words: list[dict[str, Any]], page_num: int) -> list[dict[str, Any]]:
    """
    Extract tags where the tag type is ABOVE the tag number (vertical stacking).
    Common in P&ID instrument symbols (circles/squares) where:
      - Top line: PI, MV, FIT, etc. (1-5 letters)
      - Bottom line: 6181305, 9580712, etc. (5-7 digits)
    
    Returns list of tag dicts with tag_number, coordinates, etc.
    """
    found: dict[str, dict[str, Any]] = {}
    
    # Sort words by vertical position (top to bottom), then horizontal
    sorted_words = sorted(words, key=lambda w: (float(w.get("top", 0)), float(w.get("x0", 0))))
    
    for i, top_word in enumerate(sorted_words):
        top_text = (top_word.get("text") or "").strip().upper()
        
        # Top word should be 1-5 letters (instrument/tag type)
        if not top_text or not top_text.isalpha() or not (1 <= len(top_text) <= 5):
            continue
        
        # Skip common non-tag prefixes
        if top_text in _BAD_TAG_PREFIXES or top_text in _SKIP_JOINED_PREFIX:
            continue
            
        # Get position of top word
        try:
            top_x0, top_x1 = float(top_word["x0"]), float(top_word["x1"])
            top_top, top_bottom = float(top_word["top"]), float(top_word["bottom"])
        except (KeyError, TypeError, ValueError):
            continue
        
        top_cx = (top_x0 + top_x1) / 2
        top_height = top_bottom - top_top
        
        # Look for a number below (within reasonable distance)
        max_vertical_dist = max(35.0, top_height * 3)  # Allow up to 3x the height of top text
        min_vertical_dist = max(3.0, top_height * 0.3)  # At least some separation
        
        for j in range(i + 1, len(sorted_words)):
            bottom_word = sorted_words[j]
            bottom_text = (bottom_word.get("text") or "").strip()
            
            # Bottom word should be 5-7 digits (tag number)
            if not bottom_text or not bottom_text.isdigit():
                continue
            
            if not (WILLOW_NUMERIC_SEGMENT_MIN_LEN <= len(bottom_text) <= WILLOW_NUMERIC_SEGMENT_MAX_LEN):
                continue
            
            # Get position of bottom word
            try:
                bot_x0, bot_x1 = float(bottom_word["x0"]), float(bottom_word["x1"])
                bot_top, bot_bottom = float(bottom_word["top"]), float(bottom_word["bottom"])
            except (KeyError, TypeError, ValueError):
                continue
            
            bot_cx = (bot_x0 + bot_x1) / 2
            
            # Check vertical distance
            vertical_gap = bot_top - top_bottom
            if vertical_gap < min_vertical_dist or vertical_gap > max_vertical_dist:
                # If too far vertically, stop looking for this top word
                if vertical_gap > max_vertical_dist:
                    break
                continue
            
            # Check horizontal alignment (should be roughly centered)
            horizontal_offset = abs(top_cx - bot_cx)
            max_horizontal_offset = max(20.0, (top_x1 - top_x0) * 0.8)
            
            if horizontal_offset > max_horizontal_offset:
                continue
            
            # Found a match! Create tag
            tag_number = normalize_tag_number(f"{top_text}-{bottom_text}")
            
            # Skip if already found
            if tag_number in found:
                continue
            
            # Calculate combined bounding box
            x0 = min(top_x0, bot_x0)
            x1 = max(top_x1, bot_x1)
            top = top_top
            bottom = bot_bottom
            
            # Check font size is reasonable
            if not _has_reasonable_text_size([top_word, bottom_word], min_size=6.0):
                continue
            
            # Validate the tag
            if not is_plausible_tag_number(tag_number):
                continue
            
            found[tag_number] = {
                "tag_number": tag_number,
                "page_number": page_num,
                "x": (x0 + x1) / 2,
                "y": (top + bottom) / 2,
                "tag_type": classify_tag_category(tag_number),
                "is_x_tag": False,
                "extraction_method": "vertical_stacked",
            }
            
            # Found a match for this top word, move to next top word
            break
    
    return list(found.values())


def _tags_from_page(
    page: Any,
    page_num: int,
    *,
    tag_exclude_normalized: Optional[frozenset[str]] = None,
) -> list[dict[str, Any]]:
    words = page.extract_words(x_tolerance=5, y_tolerance=3, keep_blank_chars=False) or []
    if not words:
        return []
    lines: dict[float, list[dict[str, Any]]] = defaultdict(list)
    for w in words:
        # Round to nearest 3 pixels to group words on nearly the same line
        key = round(float(w["top"]) / 3.0) * 3.0
        lines[key].append(w)
    found: dict[str, dict[str, Any]] = {}
    for rk in sorted(lines.keys()):
        lw = sorted(lines[rk], key=lambda w: float(w["x0"]))
        n = len(lw)
        for i in range(n):
            for j in range(i, min(n, i + 25)):
                sub = lw[i : j + 1]
                chunk = "".join(w.get("text", "") for w in sub).replace("\u201c", '"').replace("\u201d", '"')
                chunk_spaced = " ".join(w.get("text", "") for w in sub).replace("\u201c", '"').replace("\u201d", '"')
                # (tag_number, bbox) — bbox from the matched substring only, not the window
                candidates: list[tuple[str, tuple[float, float, float, float]]] = []
                for rx in (TAG_RE_PIPELINE, TAG_RE_PIPELINE_COMPACT, TAG_RE_PIPELINE_NOQUOTE):
                    for m in rx.finditer(chunk):
                        inch, pref, digs, suf = m.group(1), m.group(2), m.group(3), m.group(4)
                        if pref.upper() in _BAD_TAG_PREFIXES:
                            continue
                        # Reject suffixes that look like prose (TO, FROM, OF, etc.)
                        suf_upper = suf.upper()
                        if len(suf_upper) <= 2 and suf_upper in ("TO", "OF", "OR", "AT", "IN", "ON", "BY", "AS", "IS", "IF", "IT", "AN", "NO", "SO", "UP", "GO"):
                            continue
                        tn = normalize_pipeline_display(inch, pref, digs, suf)
                        if not is_plausible_pipeline_line_tag(tn):
                            continue
                        bb = _bbox_for_chunk_span(sub, chunk, m.start(), m.end())
                        candidates.append((tn, bb))
                for m in TAG_RE_PIPELINE_SPACED.finditer(chunk_spaced):
                    inch, pref, digs, suf = m.group(1), m.group(2), m.group(3), m.group(4)
                    if pref.upper() in _BAD_TAG_PREFIXES:
                        continue
                    # Reject suffixes that look like prose
                    suf_upper = suf.upper()
                    if len(suf_upper) <= 2 and suf_upper in ("TO", "OF", "OR", "AT", "IN", "ON", "BY", "AS", "IS", "IF", "IT", "AN", "NO", "SO", "UP", "GO"):
                        continue
                    tn = normalize_pipeline_display(inch, pref, digs, suf)
                    if not is_plausible_pipeline_line_tag(tn):
                        continue
                    bb = _bbox_for_chunk_spaced_span(sub, chunk_spaced, m.start(), m.end())
                    candidates.append((tn, bb))
                for m in TAG_RE_LINE_NO_SIZE.finditer(chunk):
                    pref, digs, suf = m.group(1), m.group(2), m.group(3)
                    if pref.upper() in _BAD_TAG_PREFIXES:
                        continue
                    if not _line_suffix_looks_instr_line(suf):
                        continue
                    tn = normalize_tag_number(f"{pref.upper()}-{digs}-{suf.upper()}")
                    if not is_plausible_pipeline_line_tag(tn):
                        continue
                    bb = _bbox_for_chunk_span(sub, chunk, m.start(), m.end())
                    candidates.append((tn, bb))
                for rx in (TAG_RE_PRIMARY, TAG_RE_X):
                    for m in rx.finditer(chunk):
                        if rx is TAG_RE_PRIMARY and _hyphen_compact_tag_truncated_in_source(chunk, m):
                            continue
                        tn = normalize_tag_number(m.group(0))
                        bb = _bbox_for_chunk_span(sub, chunk, m.start(), m.end())
                        candidates.append((tn, bb))
                for m in TAG_RE_SPACE.finditer(chunk_spaced):
                    if _hyphen_compact_tag_truncated_in_source(chunk_spaced, m):
                        continue
                    tn = normalize_tag_number(f"{m.group(1)}-{m.group(2)}")
                    bb = _bbox_for_chunk_spaced_span(sub, chunk_spaced, m.start(), m.end())
                    candidates.append((tn, bb))
                # Try space-separated with noise words (e.g., "ZIO U U 9881715")
                for m in TAG_RE_SPACE_WITH_NOISE.finditer(chunk_spaced):
                    if _hyphen_compact_tag_truncated_in_source(chunk_spaced, m):
                        continue
                    tn = normalize_tag_number(f"{m.group(1)}-{m.group(2)}")
                    bb = _bbox_for_chunk_spaced_span(sub, chunk_spaced, m.start(), m.end())
                    candidates.append((tn, bb))
                # Joined tags only from tight windows (avoids DFCS95800…95800…DFCS merges)
                if j - i <= 4 and len(chunk) <= 16:
                    for m in TAG_RE_JOINED.finditer(chunk):
                        if _hyphen_compact_tag_truncated_in_source(chunk, m):
                            continue
                        p1, p2 = m.group(1).upper(), m.group(2)
                        if len(p1) < 2 or len(p1) > 5 or p1 in _SKIP_JOINED_PREFIX:
                            continue
                        if len(p1 + p2) < 8:
                            continue
                        tn = normalize_tag_number(f"{p1}-{p2}")
                        bb = _bbox_for_chunk_span(sub, chunk, m.start(), m.end())
                        candidates.append((tn, bb))
                for tn_raw, bb in candidates:
                    tn = canonical_simple_extracted_tag(tn_raw)
                    nk = normalize_tag_number(tn)
                    if tag_exclude_normalized is not None and nk in tag_exclude_normalized:
                        continue
                    if tn in found:
                        continue
                    # Reject tags from tiny text (footnotes, metadata)
                    if not _has_reasonable_text_size(sub, min_size=6.0):
                        continue
                    if _is_plant_xx_sheet_continuation_reference(tn):
                        continue
                    if _is_module_banner_fake_tag(tn):
                        continue
                    if _is_detail_drawing_sheet_reference(tn):
                        continue
                    if _is_drawing_number_in_titleblock(tn):
                        continue
                    if _has_revision_placeholder(tn):
                        continue
                    if _primary_acronym_for_filter(tn) in _BAD_TAG_PREFIXES:
                        continue
                    if _bogus_I_split_from_ai_line(chunk, tn):
                        continue
                    if not is_plausible_tag_number(tn) and not is_plausible_pipeline_line_tag(tn):
                        continue
                    if not _tag_in_window(tn, chunk, chunk_spaced):
                        continue
                    x0, x1, top, bottom = bb
                    pw, ph = float(page.width), float(page.height)
                    found[tn] = {
                        "tag_number": tn,
                        "page_number": page_num,
                        "x": (x0 + x1) / 2,
                        "y": (top + bottom) / 2,
                        "page_width": pw,
                        "page_height": ph,
                        "tag_type": classify_tag_category(tn),
                        "is_x_tag": bool(TAG_RE_X.search(tn)) or ("XX" in tn and re.search(r"X{2,}", tn)),
                    }
    
    # Extract vertically stacked tags (instrument symbols with type above number)
    vertical_tags = _extract_vertical_stacked_tags(words, page_num)
    for vtag in vertical_tags:
        tn = vtag["tag_number"]
        nk = normalize_tag_number(tn)
        if tag_exclude_normalized is not None and nk in tag_exclude_normalized:
            continue
        if tn not in found:  # Don't overwrite if already found by horizontal extraction
            # Add page dimensions
            pw, ph = float(page.width), float(page.height)
            vtag["page_width"] = pw
            vtag["page_height"] = ph
            found[tn] = vtag
    
    _refine_pipeline_conflicts(found)
    _refine_truncated_hyphen_duplicates(found)
    return list(found.values())


def _extract_tags_page_range(
    pdf_path: str,
    start: int,
    end: int,
    *,
    tag_exclude_normalized: Optional[frozenset[str]] = None,
) -> list[dict[str, Any]]:
    acc: list[dict[str, Any]] = []
    with pdfplumber.open(pdf_path) as pdf:
        for idx in range(start, end):
            acc.extend(
                _tags_from_page(
                    pdf.pages[idx],
                    idx + 1,
                    tag_exclude_normalized=tag_exclude_normalized,
                )
            )
    return acc


def extract_tags(
    pdf_path: str,
    *,
    tag_exclude_normalized: Optional[frozenset[str]] = None,
) -> list[dict[str, Any]]:
    """
    Extract instrument/equipment tag numbers from every page (parallel page chunks).
    Deduplicates by tag_number — first occurrence in page order wins.
    """
    try:
        with pdfplumber.open(pdf_path) as pdf:
            n = len(pdf.pages)
        if n == 0:
            return []
        chunks = _chunk_ranges(n, _MAX_TAG_WORKERS)
        flat: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=len(chunks)) as ex:
            futs = [
                ex.submit(
                    _extract_tags_page_range,
                    pdf_path,
                    a,
                    b,
                    tag_exclude_normalized=tag_exclude_normalized,
                )
                for a, b in chunks
            ]
            for fut in as_completed(futs):
                flat.extend(fut.result())
        flat.sort(key=lambda t: (t["page_number"], t.get("y") or 0, t.get("x") or 0))
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for t in flat:
            tn = t["tag_number"]
            if tn in seen:
                continue
            seen.add(tn)
            unique.append(t)
        return unique
    except Exception:
        return []


def _point_in_rect(px: float, py: float, rect: dict[str, Any]) -> bool:
    try:
        x0, x1 = float(rect["x0"]), float(rect["x1"])
        top, bottom = float(rect["top"]), float(rect["bottom"])
    except (KeyError, TypeError, ValueError):
        return False
    return x0 <= px <= x1 and top <= py <= bottom


def _colored_rect_candidates(page: Any) -> list[dict[str, Any]]:
    """Rects with a non-white/non-black fill — built once per page for repeated point queries."""
    out: list[dict[str, Any]] = []
    for rect in page.rects or []:
        fill = rect.get("fill") or rect.get("non_stroking_color")
        if not fill or not isinstance(fill, (list, tuple)) or len(fill) < 3:
            continue
        r, g, b = float(fill[0]), float(fill[1]), float(fill[2])
        r, g, b = _norm_rgb_component(r), _norm_rgb_component(g), _norm_rgb_component(b)
        if r > 0.95 and g > 0.95 and b > 0.95:
            continue
        if r < 0.05 and g < 0.05 and b < 0.05:
            continue
        try:
            x0, x1 = float(rect["x0"]), float(rect["x1"])
            top, bottom = float(rect["top"]), float(rect["bottom"])
        except (KeyError, TypeError, ValueError):
            continue
        w, h = abs(x1 - x0), abs(bottom - top)
        if w > 520 or h > 160 or w < 2 or h < 2:
            continue
        out.append(rect)
    return out


def _smallest_colored_rect_covering_point(
    page: Any,
    px: float,
    py: float,
    *,
    max_w: float = 520,
    max_h: float = 160,
    rects: list[dict[str, Any]] | None = None,
) -> tuple[str | None, float | None]:
    """Find smallest non-white rect containing (px,py); return (hex, area)."""
    best_hex: str | None = None
    best_area = 1e18
    rect_iter = rects if rects is not None else (page.rects or [])
    for rect in rect_iter:
        fill = rect.get("fill") or rect.get("non_stroking_color")
        if not fill or not isinstance(fill, (list, tuple)) or len(fill) < 3:
            continue
        r, g, b = float(fill[0]), float(fill[1]), float(fill[2])
        r, g, b = _norm_rgb_component(r), _norm_rgb_component(g), _norm_rgb_component(b)
        if r > 0.95 and g > 0.95 and b > 0.95:
            continue
        if r < 0.05 and g < 0.05 and b < 0.05:
            continue
        try:
            x0, x1 = float(rect["x0"]), float(rect["x1"])
            top, bottom = float(rect["top"]), float(rect["bottom"])
        except (KeyError, TypeError, ValueError):
            continue
        w, h = abs(x1 - x0), abs(bottom - top)
        if w > max_w or h > max_h or w < 2 or h < 2:
            continue
        if not _point_in_rect(px, py, rect):
            continue
        area = w * h
        if area < best_area:
            best_area = area
            best_hex = _hex_from_rgb_fill(float(fill[0]), float(fill[1]), float(fill[2]))
    return best_hex, best_area if best_hex else None


def _is_likely_markup_red(hx: str | None) -> bool:
    """Bright red often used for manual review / highlighted tag text, not subsystem equipment color."""
    t = _hex_to_rgb_ints(hx)
    if not t:
        return False
    r, g, b = t
    return r >= 185 and g <= 100 and b <= 100 and r > g + 60 and r > b + 60


def _stroke_hex_from_line_like(obj: dict[str, Any]) -> str | None:
    """Stroke color from a pdfplumber line or curve dict."""
    for key in ("stroking_color", "non_stroking_color", "stroke"):
        c = obj.get(key)
        if isinstance(c, (list, tuple)) and len(c) >= 3:
            r, g, b = float(c[0]), float(c[1]), float(c[2])
            r, g, b = _norm_rgb_component(r), _norm_rgb_component(g), _norm_rgb_component(b)
            if r > 0.95 and g > 0.95 and b > 0.95:
                continue
            if r < 0.05 and g < 0.05 and b < 0.05:
                continue
            return _hex_from_rgb_fill(float(c[0]), float(c[1]), float(c[2]))
    return None


def _line_bbox_center_dist(px: float, py: float, ln: dict[str, Any]) -> float | None:
    try:
        x0, x1 = float(ln["x0"]), float(ln["x1"])
        top, bottom = float(ln["top"]), float(ln["bottom"])
    except (KeyError, TypeError, ValueError):
        return None
    mx, my = (x0 + x1) / 2, (top + bottom) / 2
    return math.hypot(px - mx, py - my)


def _line_stroke_colors_near(page: Any, px: float, py: float, max_dist: float = 130.0) -> list[str]:
    out: list[str] = []
    for ln in page.lines or []:
        d = _line_bbox_center_dist(px, py, ln)
        if d is None or d > max_dist:
            continue
        hx = _stroke_hex_from_line_like(ln)
        if hx:
            out.append(hx)
    for cr in page.curves or []:
        d = _line_bbox_center_dist(px, py, cr)
        if d is None or d > max_dist:
            continue
        hx = _stroke_hex_from_line_like(cr)
        if hx:
            out.append(hx)
    return out


def infer_subsystem_linking_color(
    page: Any,
    tx: float,
    ty: float,
    *,
    rects: list[dict[str, Any]] | None = None,
) -> str | None:
    """
    Best-effort color to match subsystem bubbles against.

    PDFs do not expose every pixel — only vector paths. We combine:
    - Fills from rects sampled *around* the tag (valve body / piping / equipment), not only on the tag text
    - Stroke colors from lines/curves near the tag (often the actual valve outline / process line)

    Manual review often colors **tag text** red; that is de-prioritized when other samples disagree.
    """
    tx, ty = float(tx), float(ty)
    offset_samples: list[str] = []
    # Away from the tag centroid — tends to hit equipment rather than a red text box
    for dx, dy in (
        (-64, 0),
        (64, 0),
        (0, 54),
        (0, -50),
        (-50, 34),
        (50, 34),
        (-54, -30),
        (54, -30),
        (-38, 42),
        (38, 42),
    ):
        hx, _ = _smallest_colored_rect_covering_point(page, tx + dx, ty + dy, rects=rects)
        if hx:
            offset_samples.append(hx)
    line_colors = _line_stroke_colors_near(page, tx, ty, 140.0)
    center_hex, _ = _smallest_colored_rect_covering_point(page, tx, ty, rects=rects)

    pool = offset_samples + line_colors
    non_markup = [h for h in pool if not _is_likely_markup_red(h)]
    if non_markup:
        return Counter(non_markup).most_common(1)[0][0]
    if pool:
        return Counter(pool).most_common(1)[0][0]
    if center_hex and not _is_likely_markup_red(center_hex):
        return center_hex
    if center_hex:
        return center_hex
    return None


def _labels_from_page(page: Any, page_num: int) -> list[dict[str, Any]]:
    """
    Subsystem label boxes: small colored rects with NN-MM text.
    Also picks up NN-MM as plain words inside a colored rect (white text on purple/green box).
    """
    out: list[dict[str, Any]] = []
    seen: set[tuple[int, str, int, int]] = set()
    
    import logging
    rect_count = len(page.rects or [])

    def _add(
        sub: str,
        hx: str,
        cx: float,
        cy: float,
        w: float,
        h: float,
    ) -> None:
        key = (page_num, sub, int(cx // 25), int(cy // 25))
        if key in seen:
            return
        seen.add(key)
        out.append(
            {
                "subsystem_number": sub,
                "hex_color": hx,
                "x": cx,
                "y": cy,
                "page_number": page_num,
                "width": w,
                "height": h,
            }
        )

    for rect in page.rects or []:
        fill = rect.get("fill") or rect.get("non_stroking_color")
        if not fill or not isinstance(fill, (list, tuple)) or len(fill) < 3:
            continue
        r, g, b = float(fill[0]), float(fill[1]), float(fill[2])
        r, g, b = _norm_rgb_component(r), _norm_rgb_component(g), _norm_rgb_component(b)
        if r > 0.95 and g > 0.95 and b > 0.95:
            continue
        if r < 0.05 and g < 0.05 and b < 0.05:
            continue
        try:
            x0, x1 = float(rect["x0"]), float(rect["x1"])
            top, bottom = float(rect["top"]), float(rect["bottom"])
        except (KeyError, TypeError, ValueError):
            continue
        w = abs(x1 - x0)
        h = abs(bottom - top)
        # Skip huge highlight regions (whole drawing areas); allow wide strip labels at line ends
        if w > 520 or h > 160:
            continue
        if w < 2 or h < 3:
            continue
        hex_color = _hex_from_rgb_fill(float(fill[0]), float(fill[1]), float(fill[2]))
        try:
            cropped = page.within_bbox((x0, top, x1, bottom))
            ttext = cropped.extract_text() or ""
            words = cropped.extract_words(x_tolerance=5, y_tolerance=3, keep_blank_chars=False) or []
        except Exception:
            continue
        combined = "".join(w.get("text", "") for w in words) if words else ttext.replace(" ", "")
        m = SUBSYSTEM_LABEL_TEXT_RE.search(combined) or SUBSYSTEM_LABEL_TEXT_RE.search(ttext.replace(" ", ""))
        if not m:
            continue
        sub = m.group(1)
        cx = (x0 + x1) / 2
        cy = (top + bottom) / 2
        _add(sub, hex_color, cx, cy, w, h)

    # Word-based: "95-02" drawn as text (often white) on top of a colored rect — rects list may omit fill
    for wobj in page.extract_words(x_tolerance=5, y_tolerance=3, keep_blank_chars=False) or []:
        raw = (wobj.get("text") or "").strip().replace("\u00a0", " ")
        compact = re.sub(r"\s+", "", raw)
        if not re.match(r"^\d{2}-\d{2}$", compact):
            continue
        sub = compact
        try:
            wx0, wx1 = float(wobj["x0"]), float(wobj["x1"])
            wtop, wbot = float(wobj["top"]), float(wobj["bottom"])
        except (KeyError, TypeError, ValueError):
            continue
        cx = (wx0 + wx1) / 2
        cy = (wtop + wbot) / 2
        ww, wh = abs(wx1 - wx0), abs(wbot - wtop)
        hx, _ = _smallest_colored_rect_covering_point(page, cx, cy)
        if hx:
            _add(sub, hx, cx, cy, max(ww, 12), max(wh, 8))

    import logging

    return out


def _extract_labels_page_range(pdf_path: str, start: int, end: int) -> list[dict[str, Any]]:
    acc: list[dict[str, Any]] = []
    with pdfplumber.open(pdf_path) as pdf:
        for idx in range(start, end):
            acc.extend(_labels_from_page(pdf.pages[idx], idx + 1))
    return acc


def _extract_combined_page_range(
    pdf_path: str,
    start: int,
    end: int,
    *,
    tag_exclude_normalized: Optional[frozenset[str]] = None,
    on_page_processed: Optional[Callable[[], None]] = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """One pdfplumber.open per chunk: tags + subsystem labels (half the I/O of two separate passes)."""
    tags_acc: list[dict[str, Any]] = []
    labels_acc: list[dict[str, Any]] = []
    with pdfplumber.open(pdf_path) as pdf:
        for idx in range(start, end):
            page = pdf.pages[idx]
            pnum = idx + 1
            
            # Extract drawing info for this specific page
            page_drawing_info = _extract_page_drawing_info(page, pnum)
            
            colored_rects = _colored_rect_candidates(page)
            page_tags = _tags_from_page(
                page,
                pnum,
                tag_exclude_normalized=tag_exclude_normalized,
            )
            for t in page_tags:
                tx, ty = t.get("x"), t.get("y")
                if tx is not None and ty is not None:
                    hx = infer_subsystem_linking_color(page, float(tx), float(ty), rects=colored_rects)
                    if hx:
                        t["tag_fill_color"] = hx
                # Add page-specific drawing info to each tag
                t["pid_drawing_number"] = page_drawing_info["drawing_number"]
                t["pid_revision"] = page_drawing_info["revision"]
            tags_acc.extend(page_tags)
            labels_acc.extend(_labels_from_page(page, pnum))
            if on_page_processed:
                on_page_processed()
    return tags_acc, labels_acc


def extract_subsystem_labels(pdf_path: str) -> list[dict[str, Any]]:
    """
    Scan every page for small colored rects containing a subsystem label (NN-MM).
    """
    try:
        with pdfplumber.open(pdf_path) as pdf:
            n = len(pdf.pages)
        if n == 0:
            return []
        chunks = _chunk_ranges(n, _MAX_LABEL_WORKERS)
        flat: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=len(chunks)) as ex:
            futs = [ex.submit(_extract_labels_page_range, pdf_path, a, b) for a, b in chunks]
            for fut in as_completed(futs):
                flat.extend(fut.result())
        return flat
    except Exception:
        return []


def enrich_tags_with_subsystems(
    tags: list[dict[str, Any]],
    subsystem_labels: list[dict[str, Any]],
    *,
    max_distance: float = 500.0,
) -> list[dict[str, Any]]:
    """
    Link each tag to a subsystem bubble (NN-MM).

    When ``tag_fill_color`` is present (see ``infer_subsystem_linking_color``: offsets +
    line strokes; avoids tag-text-only markup reds), we **prefer matching subsystem labels by color** among
    candidates near the tag, then break ties by distance. This avoids wrong subsystem
    when several bubbles are nearby but only one matches the tag/equipment color.

    Without a tag color, behavior falls back to nearest label within ``max_distance``.
    """
    by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for lab in subsystem_labels:
        by_page[int(lab["page_number"])].append(lab)

    def _spatial(tx: float, ty: float, lab: dict[str, Any]) -> float:
        lx, ly = float(lab["x"]), float(lab["y"])
        return math.hypot(tx - lx, ty - ly)

    enriched: list[dict[str, Any]] = []
    for tag in tags:
        t = dict(tag)
        pn = int(t.get("page_number") or 1)
        tx, ty = t.get("x"), t.get("y")
        tag_hex = t.get("tag_fill_color")
        labels = by_page.get(pn, [])
        nearest_sub = None
        nearest_color = None
        nearest_dist = None
        if tx is not None and ty is not None and labels:
            txf, tyf = float(tx), float(ty)
            nearby = [lab for lab in labels if _spatial(txf, tyf, lab) <= max_distance]
            # Prefer labels near the tag; if none in range, still allow matching by color on the whole page.
            pool = nearby if nearby else list(labels)

            best_lab: dict[str, Any] | None = None
            best_key: tuple[float, float] | None = None

            if tag_hex:
                for lab in pool:
                    cd = _color_distance_hex(tag_hex, lab.get("hex_color"))
                    sd = _spatial(txf, tyf, lab)
                    key = (cd, sd)
                    if best_key is None or key < best_key:
                        best_key = key
                        best_lab = lab
            else:
                best_d = 1e18
                for lab in labels:
                    sd = _spatial(txf, tyf, lab)
                    if sd < best_d:
                        best_d = sd
                        best_lab = lab
                if best_lab is not None and best_d > max_distance:
                    best_lab = None
                    best_d = None
                nearest_dist = best_d

            if best_lab is not None:
                nearest_sub = best_lab["subsystem_number"]
                nearest_color = best_lab["hex_color"]
                if nearest_dist is None:
                    nearest_dist = _spatial(txf, tyf, best_lab)
        t["nearest_subsystem"] = nearest_sub
        t["nearest_subsystem_color"] = nearest_color
        t["nearest_subsystem_distance"] = nearest_dist
        enriched.append(t)
    return enriched


def extract_all(
    pdf_path: str,
    *,
    progress_cb: Optional[Callable[[int, str], None]] = None,
    progress_lo: int = 4,
    progress_hi: int = 16,
    progress_label: str = "Reading PDF",
    tag_exclude_normalized: Optional[frozenset[str]] = None,
) -> dict[str, Any]:
    """
    Single combined pass over the PDF (parallel chunks) for tags + labels.
    Faster and more stable than calling extract_tags + extract_subsystem_labels separately.

    Optional ``progress_cb`` reports incremental percent while chunks finish (large PDFs can take minutes).
    """
    with pdfplumber.open(pdf_path) as pdf:
        n = len(pdf.pages)
    if n == 0:
        return {
            "tags": [],
            "subsystem_labels": [],
            "tag_count": 0,
            "label_count": 0,
            "subsystems_found": [],
        }
    chunks = _chunk_ranges(n, _MAX_COMBINED_WORKERS)
    nchunks = len(chunks)
    if progress_cb:
        progress_cb(progress_lo, f"{progress_label}: scanning {n} page(s) in {nchunks} part(s)…")
    tags_flat: list[dict[str, Any]] = []
    labels_flat: list[dict[str, Any]] = []
    span = max(1, progress_hi - progress_lo)
    page_lock = threading.Lock()
    pages_done = [0]

    def _on_page() -> None:
        with page_lock:
            pages_done[0] += 1
            d = pages_done[0]
            # Report every page for more granular progress
            if progress_cb and n > 0:
                p = progress_lo + int(span * min(d, n) / max(1, n))
                progress_cb(
                    min(99, max(progress_lo, p)),
                    f"{progress_label}: page {min(d, n)}/{n}…",
                )

    with ThreadPoolExecutor(max_workers=nchunks) as ex:
        futs = [
            ex.submit(
                _extract_combined_page_range,
                pdf_path,
                a,
                b,
                tag_exclude_normalized=tag_exclude_normalized,
                on_page_processed=_on_page,
            )
            for a, b in chunks
        ]
        for fut in as_completed(futs):
            tpart, lpart = fut.result()
            tags_flat.extend(tpart)
            labels_flat.extend(lpart)
    tags_flat.sort(key=lambda t: (t["page_number"], t.get("y") or 0, t.get("x") or 0))
    seen: set[str] = set()
    unique_tags: list[dict[str, Any]] = []
    for t in tags_flat:
        tn = t["tag_number"]
        if tn in seen:
            continue
        seen.add(tn)
        unique_tags.append(t)
    subs = sorted({str(l["subsystem_number"]) for l in labels_flat if l.get("subsystem_number")})
    enriched = enrich_tags_with_subsystems(unique_tags, labels_flat)
    return {
        "tags": enriched,
        "subsystem_labels": labels_flat,
        "tag_count": len(unique_tags),
        "label_count": len(labels_flat),
        "subsystems_found": subs,
    }


def _debug_sample_tags(tags: list[dict[str, Any]], n: int = 5) -> list[dict[str, Any]]:
    out = []
    for t in tags[:n]:
        out.append(
            {
                "tag_number": t.get("tag_number"),
                "page_number": t.get("page_number"),
                "tag_fill_color": t.get("tag_fill_color"),
                "nearest_subsystem": t.get("nearest_subsystem"),
                "nearest_subsystem_color": t.get("nearest_subsystem_color"),
                "nearest_subsystem_distance": t.get("nearest_subsystem_distance"),
            }
        )
    return out


def build_extraction_debug(result: dict[str, Any]) -> dict[str, Any]:
    tags = result.get("tags") or []
    return {
        "total_tags_extracted": result.get("tag_count", 0),
        "total_labels_extracted": result.get("label_count", 0),
        "subsystems_found": result.get("subsystems_found") or [],
        "sample_tags": _debug_sample_tags(tags, 5),
    }


def _extract_page_drawing_info(page: Any, page_num: int) -> dict[str, Any]:
    """
    Extract drawing number and revision from a single page's titleblock.
    Focuses on bottom-right corner where titleblocks typically are.
    """
    out: dict[str, Any] = {
        "drawing_number": None,
        "revision": None,
    }
    try:
        w, h = float(page.width), float(page.height)
        # Bottom 15% of page (titleblock area)
        crop = page.within_bbox((0, h * 0.85, w, h))
        text = crop.extract_text() or ""
        full_text = page.extract_text() or ""
        
        # Try to find drawing number
        for m in DRAWING_NUM_RE.finditer(text + "\n" + full_text):
            cand = m.group(1).strip()
            if len(cand) > 20:
                out["drawing_number"] = cand
                break
        
        if not out["drawing_number"]:
            # Fallback pattern for drawing numbers
            m2 = re.search(
                r"([A-Z]{3,5}-[A-Z0-9]{2,5}-[A-Z]{3}-[A-Z]{3,4}-[A-Z]{3}-[0-9]{5}-[A-Z0-9]+-[0-9]{2,})",
                text + full_text,
                re.I,
            )
            if m2:
                out["drawing_number"] = m2.group(1).strip()
        
        # Extract revision from titleblock area
        out["revision"] = _extract_revision(text)
        
    except Exception:
        pass
    
    return out


def extract_drawing_info(pdf_path: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "drawing_number": None,
        "drawing_title": None,
        "drawing_type": None,
        "plant": None,
        "revision": None,
        "page_count": 0,
        "extraction_error": None,
    }
    try:
        with pdfplumber.open(pdf_path) as pdf:
            out["page_count"] = len(pdf.pages)
            if not pdf.pages:
                return out
            page = pdf.pages[0]
            w, h = float(page.width), float(page.height)
            crop = page.within_bbox((0, h * 0.85, w, h))
            text = crop.extract_text() or ""
            full_text = page.extract_text() or ""
            blob = (text + "\n" + full_text).upper()

            for m in DRAWING_NUM_RE.finditer(text + "\n" + full_text):
                cand = m.group(1).strip()
                if len(cand) > 20:
                    out["drawing_number"] = cand
                    break
            if not out["drawing_number"]:
                m2 = re.search(
                    r"([A-Z]{3,5}-[A-Z0-9]{2,5}-[A-Z]{3}-[A-Z]{3,4}-[A-Z]{3}-[0-9]{5}-[A-Z0-9]+-[0-9]{2,})",
                    text + full_text,
                    re.I,
                )
                if m2:
                    out["drawing_number"] = m2.group(1).strip()

            lines = [ln.strip() for ln in (text + "\n" + full_text).splitlines() if ln.strip()]
            if lines and not out["drawing_title"]:
                for ln in lines:
                    if len(ln) > 15 and not DRAWING_NUM_RE.search(ln):
                        if "SHEET" not in ln.upper() and "SCALE" not in ln.upper():
                            out["drawing_title"] = ln[:500]
                            break

            out["drawing_type"] = _infer_drawing_type(text + full_text)
            out["revision"] = _extract_revision(text + full_text)
            if out["drawing_number"]:
                out["plant"] = _infer_plant_from_drawing_number(out["drawing_number"])
            if not out["drawing_type"]:
                out["drawing_type"] = _infer_drawing_type(blob)
    except Exception as e:
        out["extraction_error"] = str(e)[:500]
    return out


def extract_colors_near_tags(pdf_path: str, tags: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach color_hex to each tag using rects near x,y (non-systemized comparison path)."""
    enriched = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for tag in tags:
                t = dict(tag)
                page_num = int(t.get("page_number") or 1) - 1
                if page_num < 0 or page_num >= len(pdf.pages):
                    t["color_hex"] = None
                    enriched.append(t)
                    continue
                page = pdf.pages[page_num]
                px, py = t.get("x"), t.get("y")
                best_hex = None
                best_d = 99999.0
                if px is not None and py is not None:
                    for rect in page.rects or []:
                        fill = rect.get("fill") or rect.get("non_stroking_color")
                        if not fill:
                            continue
                        if isinstance(fill, (list, tuple)) and len(fill) >= 3:
                            r, g, b = float(fill[0]), float(fill[1]), float(fill[2])
                        else:
                            continue
                        rr, gg, bb = r, g, b
                        if rr <= 1:
                            rr, gg, bb = rr * 255, gg * 255, bb * 255
                        if rr > 240 and gg > 240 and bb > 240:
                            continue
                        if rr < 15 and gg < 15 and bb < 15:
                            continue
                        rx = (float(rect["x0"]) + float(rect["x1"])) / 2
                        ry = (float(rect["top"]) + float(rect["bottom"])) / 2
                        d = ((rx - px) ** 2 + (ry - py) ** 2) ** 0.5
                        if d < 50 and d < best_d:
                            best_d = d
                            best_hex = _hex_from_rgb(r, g, b)
                t["color_hex"] = best_hex
                enriched.append(t)
    except Exception:
        for tag in tags:
            t = dict(tag)
            t["color_hex"] = None
            enriched.append(t)
    return enriched


def detect_comparison_type(role_a: str, role_b: str) -> str:
    a, b = role_a, role_b
    pair = {a, b}
    if pair == {"current_systemized", "new_engineering"}:
        return "new_vs_systemized"
    if pair == {"current_systemized", "prior_systemized"}:
        return "systemized_vs_systemized"
    if a == "new_engineering" and b == "new_engineering":
        return "new_vs_new"
    if "current_systemized" in pair and "new_engineering" in pair:
        return "new_vs_systemized"
    if "current_systemized" in pair and "prior_systemized" in pair:
        return "systemized_vs_systemized"
    return "new_vs_new"
