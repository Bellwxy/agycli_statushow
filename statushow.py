#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""agy-statusline: Zero-inflation real-time context & compaction monitor for Antigravity CLI.

Reads the authoritative server-pushed CheckpointConfig.max_context_tokens directly
from ~/.gemini/antigravity-cli/conversations/<conversation_id>.db (Protobuf wire fields:
gen_metadata f1.f9.f10.f4 and executor_metadata f10.f2.f5), so any backend limit
change (e.g. 256K -> 512K -> 900K -> 1M) is reflected automatically on Turn 1
without hardcoding model limits.
"""

import glob
import json
import os
import re
import sqlite3
import sys
import tempfile
import unicodedata
from urllib.parse import quote


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _display_width(text):
    clean = _ANSI_RE.sub("", text)
    w = 0
    for ch in clean:
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w


def _pack_lines(parts, sep, max_w):
    if not parts:
        return []
    sep_w = _display_width(sep)
    widths = [_display_width(p) for p in parts]
    total_w = sum(widths) + sep_w * (len(parts) - 1)
    if total_w <= max_w:
        return [sep.join(parts)], True

    line1 = [parts[0]]
    w1 = widths[0]
    split_idx = 1
    for i in range(1, len(parts)):
        if w1 + sep_w + widths[i] <= max_w:
            line1.append(parts[i])
            w1 += sep_w + widths[i]
            split_idx = i + 1
        else:
            break

    if split_idx >= len(parts):
        return [sep.join(line1)], w1 <= max_w

    line2 = parts[split_idx:]
    w2 = sum(widths[split_idx:]) + sep_w * (len(line2) - 1)
    return [sep.join(line1), sep.join(line2)], (w1 <= max_w and w2 <= max_w)


def _render_adaptive(tiers, sep, max_w):
    for parts in tiers:
        if not parts:
            continue
        lines, fits = _pack_lines(parts, sep, max_w)
        if fits:
            return lines
    lines, _ = _pack_lines(tiers[-1], sep, max_w)
    return lines


def fmt_tok(n):
    n = int(n or 0)
    if n >= 1000000:
        val = n / 1048576.0 if n % 1048576 == 0 else n / 1000000.0
        s = "{:.1f}".format(val)
        return (s[:-2] if s.endswith(".0") else s) + "M"
    if n >= 1000:
        s = "{:.1f}".format(n / 1000.0)
        return (s[:-2] if s.endswith(".0") else s) + "K"
    return str(n)


def fmt_tps(val):
    v = float(val or 0.0)
    return "{:.0f}".format(v) if v >= 100.0 else "{:.1f}".format(v)


def _read_git_head_branch(start_dir):
    """Reads current Git branch (or short SHA) by walking up to .git/HEAD without subprocess."""
    if not start_dir or not os.path.isdir(start_dir):
        return ""
    cur = os.path.abspath(start_dir)
    for _ in range(32):
        dot_git = os.path.join(cur, ".git")
        git_dir = ""
        if os.path.isdir(dot_git):
            git_dir = dot_git
        elif os.path.isfile(dot_git):
            try:
                with open(dot_git, "r", encoding="utf-8", errors="ignore") as gf:
                    first = gf.readline().strip()
                if first.lower().startswith("gitdir:"):
                    target = first[7:].strip()
                    git_dir = target if os.path.isabs(target) else os.path.normpath(os.path.join(cur, target))
            except Exception:
                return ""
        if git_dir:
            head_file = os.path.join(git_dir, "HEAD")
            try:
                with open(head_file, "r", encoding="utf-8", errors="ignore") as hf:
                    head = hf.readline().strip()
                if head.startswith("ref:"):
                    ref = head[4:].strip()
                    if ref.startswith("refs/heads/"):
                        return ref[11:]
                    return ref.rsplit("/", 1)[-1]
                if len(head) >= 7:
                    return head[:7]
            except Exception:
                return ""
            return ""
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return ""


def resolve_git_branch(data):
    """Resolves Git branch from payload metadata or workspace directory."""
    wt = data.get("worktree")
    if isinstance(wt, dict) and wt.get("branch"):
        return str(wt["branch"]).strip()
    if data.get("git_branch"):
        return str(data["git_branch"]).strip()

    candidates = []
    if data.get("cwd"):
        candidates.append(data["cwd"])
    ws = data.get("workspace")
    if isinstance(ws, dict):
        if ws.get("current_dir"):
            candidates.append(ws["current_dir"])
        if ws.get("project_dir"):
            candidates.append(ws["project_dir"])
    elif isinstance(ws, str) and ws:
        candidates.append(ws)
    if data.get("project_dir"):
        candidates.append(data["project_dir"])
    try:
        candidates.append(os.getcwd())
    except Exception:
        pass

    for path in candidates:
        branch = _read_git_head_branch(path)
        if branch:
            return branch
    return ""


# ─── Minimal Protobuf Wire Decoder (Zero External Dependencies) ──────────────
def _decode_varint(buf, o):
    res = 0
    shift = 0
    n = len(buf)
    while o < n:
        b = buf[o]
        o += 1
        res |= (b & 0x7F) << shift
        if not (b & 0x80):
            return res, o
        shift += 7
    return None, o


def _pb_iter(buf):
    if not buf:
        return
    o = 0
    n = len(buf)
    while o < n:
        tag, o = _decode_varint(buf, o)
        if tag is None:
            break
        fn = tag >> 3
        wire = tag & 7
        if wire == 0:
            v, o = _decode_varint(buf, o)
            if v is None:
                break
            yield fn, wire, v
        elif wire == 2:
            ln, o = _decode_varint(buf, o)
            if ln is None or o + ln > n:
                break
            yield fn, wire, buf[o : o + ln]
            o += ln
        elif wire == 1:
            if o + 8 > n:
                break
            o += 8
        elif wire == 5:
            if o + 4 > n:
                break
            o += 4
        else:
            break


def _pb_get_sub(buf, field_num):
    for fn, wire, val in _pb_iter(buf):
        if fn == field_num and wire == 2:
            return val
    return None


def _pb_get_varint(buf, field_num):
    for fn, wire, val in _pb_iter(buf):
        if fn == field_num and wire == 0:
            return val
    return None


def _pb_parse_ts(buf):
    """Decodes google.protobuf.Timestamp (f1=seconds, f2=nanos) to float seconds."""
    if not buf:
        return 0.0
    sec = 0
    nsec = 0
    for fn, wire, val in _pb_iter(buf):
        if wire == 0:
            if fn == 1:
                sec = val
            elif fn == 2:
                nsec = val
    return float(sec) + float(nsec) / 1e9 if sec > 0 else 0.0


def _parse_step_tps_sample(meta):
    """Extracts (output_tokens, duration_seconds) from a PLANNER_RESPONSE step metadata blob."""
    if not meta:
        return None
    t_start = 0.0
    t_end = 0.0
    t_end_fb = 0.0
    out_tokens = 0
    for fn, wire, val in _pb_iter(meta):
        if wire != 2:
            continue
        if fn == 1:
            t_start = _pb_parse_ts(val)
        elif fn == 7:
            t_end = _pb_parse_ts(val)
        elif fn in (8, 32) and t_end_fb == 0.0:
            t_end_fb = _pb_parse_ts(val)
        elif fn == 9:
            v = _pb_get_varint(val, 3)
            if v:
                out_tokens = int(v)
    t_finish = t_end or t_end_fb
    dt = t_finish - t_start
    if out_tokens > 0 and 0.05 < dt < 3600.0:
        return out_tokens, dt
    return None


def _sqlite_ro_uri(db_path):
    norm = os.path.abspath(db_path).replace("\\", "/")
    if not norm.startswith("/"):
        norm = "/" + norm
    return "file:{}?mode=ro".format(quote(norm, safe="/:"))


def _extract_limit_from_conn(conn):
    """Reads server-pushed CheckpointConfig.max_context_tokens from an open SQLite connection."""
    # 1. Latest generation metadata (f1.f9.f10.f4) reflects active turn's live limit
    row = conn.execute("SELECT data FROM gen_metadata ORDER BY idx DESC LIMIT 1").fetchone()
    if row and row[0]:
        b = _pb_get_sub(row[0], 1)
        b = _pb_get_sub(b, 9)
        b = _pb_get_sub(b, 10)
        lim = _pb_get_varint(b, 4)
        if lim and 16000 <= lim <= 10000000:
            return int(lim)
    # 2. Executor CascadeConfig.CheckpointConfig.max_context_tokens (f10.f2.f5)
    erow = conn.execute("SELECT data FROM executor_metadata ORDER BY idx DESC LIMIT 1").fetchone()
    if erow and erow[0]:
        b = _pb_get_sub(erow[0], 10)
        b = _pb_get_sub(b, 2)
        lim = _pb_get_varint(b, 5)
        if lim and 16000 <= lim <= 10000000:
            return int(lim)
    return None


def _extract_limit_from_db(db_path):
    """Reads server-pushed CheckpointConfig.max_context_tokens from conversation SQLite DB."""
    if not db_path or not os.path.isfile(db_path):
        return None
    conn = None
    try:
        conn = sqlite3.connect(_sqlite_ro_uri(db_path), uri=True, timeout=0.15)
        return _extract_limit_from_conn(conn)
    except Exception:
        return None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return None


def _update_tps_from_conn(conn, entry):
    """Incrementally scans completed PLANNER_RESPONSE steps (step_type=15, status=3) for TPS."""
    last_idx = int(entry.get("last_idx", -1))
    turns = int(entry.get("turns", 0))
    tot_out = int(entry.get("tot_out", 0))
    tot_dt = float(entry.get("tot_dt", 0.0))
    last_tps = float(entry.get("last_tps", 0.0))

    rows = conn.execute(
        "SELECT idx, metadata FROM steps WHERE step_type = 15 AND status = 3 AND idx > ? ORDER BY idx ASC",
        (last_idx,),
    ).fetchall()
    for idx, meta in rows:
        last_idx = int(idx)
        sample = _parse_step_tps_sample(meta)
        if sample:
            out_tok, dt = sample
            turns += 1
            tot_out += out_tok
            tot_dt += dt
            last_tps = float(out_tok) / dt

    return {
        "last_idx": last_idx,
        "turns": turns,
        "tot_out": tot_out,
        "tot_dt": round(tot_dt, 4),
        "last_tps": round(last_tps, 2),
    }


def resolve_db_metrics(conv_id, t_path, cache):
    """Resolves server compaction limit and incremental TPS stats for the active conversation."""
    base_dir = os.path.expanduser("~/.gemini/antigravity-cli")
    if t_path:
        expanded = os.path.expanduser(t_path).replace("\\", "/")
        marker = "/brain/"
        pos = expanded.find(marker)
        if pos > 0:
            base_dir = expanded[:pos]
            if not conv_id:
                rest = expanded[pos + len(marker) :]
                conv_id = rest.split("/")[0]

    conv_dir = os.path.join(base_dir, "conversations")
    db_path = os.path.join(conv_dir, "{}.db".format(conv_id)) if conv_id else ""
    tps_stats = None

    if db_path and os.path.isfile(db_path):
        try:
            db_sz = os.path.getsize(db_path)
            wal_path = db_path + "-wal"
            wal_sz = os.path.getsize(wal_path) if os.path.isfile(wal_path) else 0
            sig = "{}:{}".format(db_sz, wal_sz)
        except Exception:
            sig = ""

        db_cache = cache.setdefault("_db_limits", {})
        tps_cache = cache.setdefault("_db_tps", {})
        cached_lim = db_cache.get(db_path)
        cached_tps = tps_cache.get(db_path)

        lim_hit = isinstance(cached_lim, dict) and cached_lim.get("sig") == sig and cached_lim.get("limit")
        tps_hit = isinstance(cached_tps, dict) and cached_tps.get("sig") == sig
        if lim_hit and tps_hit:
            return int(cached_lim["limit"]), cached_tps

        lim = int(cached_lim["limit"]) if lim_hit else None
        conn = None
        try:
            conn = sqlite3.connect(_sqlite_ro_uri(db_path), uri=True, timeout=0.15)
            if not lim_hit:
                lim = _extract_limit_from_conn(conn)
            if not tps_hit:
                base_entry = cached_tps if isinstance(cached_tps, dict) else {}
                tps_stats = _update_tps_from_conn(conn, base_entry)
                tps_stats["sig"] = sig
                if len(tps_cache) > 16 and db_path not in tps_cache:
                    tps_cache.pop(next(iter(tps_cache)), None)
                tps_cache[db_path] = tps_stats
            else:
                tps_stats = cached_tps
        except Exception:
            tps_stats = cached_tps if isinstance(cached_tps, dict) else None
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

        if lim:
            if len(db_cache) > 16 and db_path not in db_cache:
                db_cache.pop(next(iter(db_cache)), None)
            db_cache[db_path] = {"sig": sig, "limit": lim}
            cache["_last_known_limit"] = lim
            return lim, tps_stats

    # Brand-new session before Turn 1: inherit most recent conversation DB's server limit
    if cache.get("_last_known_limit"):
        return int(cache["_last_known_limit"]), tps_stats

    if os.path.isdir(conv_dir):
        try:
            dbs = sorted(
                glob.glob(os.path.join(conv_dir, "*.db")),
                key=os.path.getmtime,
                reverse=True,
            )[:5]
            for cand in dbs:
                lim = _extract_limit_from_db(cand)
                if lim:
                    cache["_last_known_limit"] = lim
                    return lim, tps_stats
        except Exception:
            pass

    return 512000, tps_stats


def _cache_path():
    uid = getattr(os, "getuid", lambda: 0)()
    return os.path.join(tempfile.gettempdir(), "agy_ctx_status_{}.json".format(uid))


def load_cache():
    cache_file = _cache_path()
    try:
        if os.path.isfile(cache_file):
            with open(cache_file, "r", encoding="utf-8") as cf:
                return cache_file, (json.load(cf) or {})
    except Exception:
        pass
    return cache_file, {}


def save_cache(cache_file, cache):
    try:
        tmp_file = "{}.{}".format(cache_file, os.getpid())
        with open(tmp_file, "w", encoding="utf-8") as cf:
            json.dump(cache, cf)
        os.replace(tmp_file, cache_file)
    except Exception:
        pass


def scan_transcript_incremental(t_path, cache):
    """Incrementally scans transcript.jsonl for checkpoints, peak context, and last turn."""
    if not t_path:
        return None
    t_path = os.path.expanduser(t_path)
    if not os.path.isfile(t_path):
        return None

    try:
        st = os.stat(t_path)
        f_ino = int(getattr(st, "st_ino", 0))
        f_size = int(st.st_size)
    except Exception:
        return None

    t_map = cache.setdefault("_transcripts", {})
    entry = t_map.get(t_path)
    if (
        isinstance(entry, dict)
        and entry.get("ino") == f_ino
        and isinstance(entry.get("offset"), int)
        and 0 <= entry["offset"] <= f_size
    ):
        offset = entry["offset"]
        ckpts = int(entry.get("ckpts") or 0)
        peak_ctx = int(entry.get("peak_ctx") or 0)
        tot_out = int(entry.get("tot_out") or 0)
        last_turn = entry.get("last_turn")
    else:
        offset = 0
        ckpts = 0
        peak_ctx = 0
        tot_out = 0
        last_turn = None

    if offset < f_size:
        try:
            with open(t_path, "rb") as f:
                f.seek(offset)
                raw_bytes = f.read()
            last_nl = raw_bytes.rfind(b"\n")
            if last_nl >= 0:
                chunk = raw_bytes[: last_nl + 1]
                offset += last_nl + 1
                for bline in chunk.splitlines():
                    if b'"CHECKPOINT"' in bline:
                        try:
                            obj = json.loads(bline.decode("utf-8", "ignore"))
                            if obj.get("type") == "CHECKPOINT":
                                ckpts += 1
                        except Exception:
                            pass
                    elif b'"input_tokens"' in bline and b'"PLANNER_RESPONSE"' in bline:
                        try:
                            obj = json.loads(bline.decode("utf-8", "ignore"))
                        except Exception:
                            continue
                        if obj.get("type") == "PLANNER_RESPONSE" and isinstance(obj.get("input_tokens"), int):
                            inp = int(obj.get("input_tokens") or 0)
                            c_read = int(obj.get("cache_read_tokens") or 0)
                            c_create = int(obj.get("cache_creation_tokens") or 0)
                            out = int(obj.get("output_tokens") or 0)
                            tot_out += out
                            turn_total = inp + c_create + c_read + out
                            if turn_total > peak_ctx:
                                peak_ctx = turn_total
                            last_turn = {
                                "input_tokens": inp,
                                "cache_read_input_tokens": c_read,
                                "cache_creation_input_tokens": c_create,
                                "output_tokens": out,
                            }
                if len(t_map) > 12 and t_path not in t_map:
                    t_map.pop(next(iter(t_map)), None)
                t_map[t_path] = {
                    "ino": f_ino,
                    "offset": offset,
                    "ckpts": ckpts,
                    "peak_ctx": peak_ctx,
                    "tot_out": tot_out,
                    "last_turn": last_turn,
                }
        except Exception:
            pass

    return {
        "ckpts": ckpts,
        "peak_ctx": peak_ctx,
        "tot_out": tot_out,
        "last_turn": last_turn,
    }


def main():
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)

    R = "\033[0m"
    B = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    CYAN = "\033[36m"
    MAGENTA = "\033[35m"
    BLUE = "\033[94m"

    cols = int(data.get("terminal_width") or 100)

    model_obj = data.get("model")
    model_name = ""
    if isinstance(model_obj, dict):
        model_name = model_obj.get("display_name") or model_obj.get("id") or ""
        effort = model_obj.get("effort") or ""
        if effort and effort.lower() not in model_name.lower():
            model_name = "{} ({})".format(model_name, effort)
    elif isinstance(model_obj, str):
        model_name = model_obj

    cache_file, cache = load_cache()
    before_snapshot = json.dumps(cache, sort_keys=True)

    conv_id = data.get("conversation_id") or data.get("session_id") or ""
    t_path = data.get("transcript_path") or ""

    t_stats = scan_transcript_incremental(t_path, cache)
    ckpts = int(t_stats["ckpts"]) if t_stats else 0
    peak_ctx = int(t_stats["peak_ctx"]) if t_stats else 0

    server_limit, tps_stats = resolve_db_metrics(conv_id, t_path, cache)

    if json.dumps(cache, sort_keys=True) != before_snapshot:
        save_cache(cache_file, cache)

    cw = data.get("context_window") or {}
    raw_win_size = int(cw.get("context_window_size") or 0)
    raw_used_pct = float(cw.get("used_percentage") or 0.0)
    tot_out = int(cw.get("total_output_tokens") or 0)
    if not tot_out and t_stats:
        tot_out = int(t_stats.get("tot_out") or 0)

    cur = cw.get("current_usage")
    if not isinstance(cur, dict) and t_stats and isinstance(t_stats.get("last_turn"), dict):
        cur = t_stats["last_turn"]

    has_turn = isinstance(cur, dict)
    inp = int(cur.get("input_tokens") or 0) if has_turn else 0
    c_create = int(cur.get("cache_creation_input_tokens") or 0) if has_turn else 0
    c_read = int(cur.get("cache_read_input_tokens") or 0) if has_turn else 0
    turn_out = int(cur.get("output_tokens") or 0) if has_turn else 0

    prompt_ctx = inp + c_create + c_read
    active_ctx = prompt_ctx + turn_out

    if active_ctx == 0 and raw_used_pct > 0 and raw_win_size > 0:
        active_ctx = int(round(raw_win_size * raw_used_pct / 100.0))

    if active_ctx > peak_ctx:
        peak_ctx = active_ctx

    # Effective ceiling = min(model physical window, server-pushed CheckpointConfig.max_context_tokens)
    if raw_win_size > 0 and server_limit > 0:
        effective_limit = min(raw_win_size, server_limit)
    else:
        effective_limit = server_limit or raw_win_size or 512000

    real_pct = (active_ctx * 100.0 / float(effective_limit)) if active_ctx > 0 else 0.0

    if real_pct >= 85.0:
        pct_color = RED
    elif real_pct >= 65.0:
        pct_color = YELLOW
    else:
        pct_color = CYAN

    sep = "{dim} · {r}".format(dim=DIM, r=R)
    branch = resolve_git_branch(data)
    if branch and len(branch) > 28:
        branch = branch[:25] + "..."

    def build_parts(compact=False, include_model=True, drop_extras=False):
        segs = []
        if include_model and model_name:
            segs.append("{m}◈ {name}{r}".format(m=MAGENTA, name=model_name, r=R))
        if branch:
            segs.append("{blue}({br}){r}".format(blue=BLUE, br=branch, r=R))

        if active_ctx > 0 or has_turn:
            tok_lbl = "{}/{}".format(fmt_tok(active_ctx), fmt_tok(effective_limit))
            segs.append("{dim}上下文{r} {pc}{b}{pct:.1f}%{r} {dim}({tok}){r}".format(
                dim=DIM, r=R, pc=pct_color, b=B, pct=real_pct, tok=tok_lbl
            ))
        else:
            segs.append("{dim}上下文{r} {b}0.0%{r} {dim}(上限 {lim}){r}".format(
                dim=DIM, r=R, b=B, lim=fmt_tok(effective_limit)
            ))

        if ckpts > 0:
            if not compact and peak_ctx > 0:
                segs.append("{y}压缩×{n}{r}{dim}(峰{pk}){r}".format(
                    y=YELLOW, n=ckpts, r=R, dim=DIM, pk=fmt_tok(peak_ctx)
                ))
            else:
                segs.append("{y}压缩×{n}{r}".format(y=YELLOW, n=ckpts, r=R))

        if prompt_ctx > 0:
            cache_pct = c_read * 100.0 / float(prompt_ctx)
            cache_color = GREEN if cache_pct >= 50.0 else DIM
            if not compact and ckpts == 0:
                segs.append("{dim}缓存{r} {cc}{pct:.0f}%{r} {dim}({cr}){r}".format(
                    dim=DIM, r=R, cc=cache_color, pct=cache_pct, cr=fmt_tok(c_read)
                ))
            else:
                segs.append("{dim}缓存{r} {cc}{pct:.0f}%{r}".format(
                    dim=DIM, r=R, cc=cache_color, pct=cache_pct
                ))

        if not drop_extras and tot_out > 0:
            segs.append("{dim}输出{r} {b}{out}{r}".format(dim=DIM, r=R, b=B, out=fmt_tok(tot_out)))

        if isinstance(tps_stats, dict) and float(tps_stats.get("last_tps") or 0.0) > 0:
            last_tps = float(tps_stats["last_tps"])
            tps_color = GREEN if last_tps >= 60.0 else (CYAN if last_tps >= 25.0 else YELLOW)
            tps_dt = float(tps_stats.get("tot_dt") or 0.0)
            tps_out = int(tps_stats.get("tot_out") or 0)
            avg_tps = (float(tps_out) / tps_dt) if tps_dt > 0 and tps_out > 0 else 0.0
            if not compact and int(tps_stats.get("turns") or 0) >= 2 and avg_tps > 0:
                segs.append("{dim}TPS{r} {tc}{cur}{r}{dim}(均{avg}){r}".format(
                    dim=DIM, r=R, tc=tps_color, cur=fmt_tps(last_tps), avg=fmt_tps(avg_tps)
                ))
            else:
                segs.append("{dim}TPS{r} {tc}{cur}{r}".format(
                    dim=DIM, r=R, tc=tps_color, cur=fmt_tps(last_tps)
                ))

        cost_obj = data.get("cost")
        if not drop_extras and isinstance(cost_obj, dict) and cost_obj.get("total_usd") is not None:
            usd = float(cost_obj.get("total_usd") or 0.0)
            if usd > 0:
                usd_fmt = "${:.3f}".format(usd) if usd < 0.01 else "${:.2f}".format(usd)
                segs.append("{dim}费用{r} {b}{u}{r}".format(dim=DIM, r=R, b=B, u=usd_fmt))

        if real_pct >= 85.0:
            segs.append("{red}{b}即将触发压缩{r}".format(red=RED, b=B, r=R))

        return segs

    max_w = max(36, cols - 2)
    lines = _render_adaptive(
        [
            build_parts(compact=False, include_model=True),
            build_parts(compact=True, include_model=True),
            build_parts(compact=True, include_model=False),
            build_parts(compact=True, include_model=False, drop_extras=True),
        ],
        sep,
        max_w,
    )
    sys.stdout.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.stdout.write("\n")
        sys.exit(0)
