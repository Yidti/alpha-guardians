#!/usr/bin/env python3
"""Alpha 安檢門（Alpha Security Gate）：送模擬之前，先抓出一定會失敗的表達式。

只用 Python 標準函式庫，離線執行：讀你自己匯出的欄位／運算子清單（catalog_export.py），
不呼叫 simulation API、不送任何東西給平台。

會擋（BLOCKED，送出去一定錯）：
  - 欄位在這個 region/universe/delay 不存在（打錯字、別區的欄位、已下架）
  - 運算子不在你帳號的 operators 清單
  - 運算子參數個數不對、括號不成對
  - VECTOR 欄位沒有先用 vec_*（例如 vec_avg）包起來
  - template 的 <佔位符> 沒有給值
只提醒（WARNING，不擋）：
  - gene 只是在換分組／中性化方式（產出彼此相關常常很高）
  - neutralization 屬 Power Pool 家族（產出不能走 Regular 繳交）
  - 你在 config 裡標記暫停模擬的 region

用法：
    # 一行一個表達式
    python gate.py my_alphas.txt --region USA --universe TOP3000 --delay 1 --catalog catalog/
    # GA template（template＋gene_pool）或 seeds 檔（JSON）
    python gate.py my_template.json --region EUR --universe TOP2500 --delay 1 --catalog catalog/
結束代碼：0＝沒有會擋的問題，1＝有，2＝無法判斷（例如沒有對應的 catalog）。
"""
import argparse
import json
import re
import sys
from pathlib import Path

GROUPING = {'market', 'sector', 'industry', 'subindustry', 'country', 'exchange', 'currency'}
CONSTANTS = {'true', 'false', 'nan', 'inf', 'null', 'none'}
# Power Pool 家族的 neutralization 會帶 PURE_POWER_POOL_THEME，不能走 Regular 繳交。
PP_NEUTRALIZATIONS = {'FAST', 'SLOW', 'SLOW_FAST', 'SLOW_AND_FAST', 'CROWDING', 'RAM',
                      'REVERSION_AND_MOMENTUM', 'STATISTICAL'}
IDENT = re.compile(r'\b[A-Za-z_][A-Za-z0-9_]*\b')
PLACEHOLDER = re.compile(r'<([A-Za-z0-9_]+)>')
PYTHON = re.compile(r'@alpha\(|^\s*(def|import|from)\s', re.M)
MAX_EXPANSIONS = 5000
MAX_COMPOUND = 2000


def _load(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def _rows(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get('results'), list):
        return data['results']
    return list(data.values()) if isinstance(data, dict) else []


def load_catalog(data_dir, region, universe, delay):
    """Field ids, operator names and recently removed fields for one scope.
    Falls back to every synced universe of the region when the exact one is not tracked."""
    data_dir = Path(data_dir)
    exact = f'datafields_{region}_{universe}_{delay}d_latest'
    stems = [exact] if (data_dir / f'{exact}.ids').exists() or (data_dir / f'{exact}.json').exists() else \
        sorted({p.stem for p in data_dir.glob(f'datafields_{region}_*_{delay}d_latest.*') if p.suffix in ('.ids', '.json')})
    fields = set()
    for stem in stems:
        ids = data_dir / f'{stem}.ids'
        if ids.exists():
            fields |= set(ids.read_text(encoding='utf-8').split())
        else:
            fields |= {r.get('id') for r in _rows(_load(data_dir / f'{stem}.json')) if isinstance(r, dict)}
    op_rows = [r for r in _rows(_load(data_dir / 'operators.json')) if isinstance(r, dict)]
    ops = {r.get('name') for r in op_rows}
    # 參數數量來源：operators.json 每個 operator 的 definition 字串（例如 "ts_zscore(x, d)"）；
    # 沒有 definition 或解析不出來的 operator 不檢查參數數（不猜）。
    arity = {}
    for r in op_rows:
        parsed = parse_arity(r.get('definition'), r.get('name'))
        if parsed:
            arity[r['name']] = parsed
    removed = {}
    changes = data_dir / '.catalog-changes.jsonl'
    if changes.exists():
        for line in changes.read_text(encoding='utf-8').splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if entry.get('scope', '').startswith(f'datafields_{region}_'):
                for name in entry.get('removed', []):
                    removed[name] = entry.get('at', '')[:10]
                for name in entry.get('added', []):
                    removed.pop(name, None)
    # VECTOR fields (per the synced JSON) must be reduced with a vec_* operator before anything else.
    vectors = set()
    for stem in stems:
        for r in _rows(_load(data_dir / f'{stem}.json')) if (data_dir / f'{stem}.json').exists() else []:
            if isinstance(r, dict) and str(r.get('type') or '').upper() == 'VECTOR' and r.get('id'):
                vectors.add(r['id'])
    return {'fields': fields, 'ops': ops, 'removed': removed, 'sources': stems,
            'exact_universe': stems == [exact], 'vectors': vectors, 'arity': arity}


def parse_arity(definition, name=None):
    """(min_args, max_args or None=不限) from a definition like `rank(x, rate=2)`; None when it cannot tell.
    有 `=` 的參數是選填；`..`／`...` 代表可變長度。keyword 參數也算一個參數。"""
    if not isinstance(definition, str):
        return None
    m = re.match(r'\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(', definition)
    if not m or (name and m.group(1) != name):
        return None
    depth, start, end = 1, m.end(), None
    for i in range(start, len(definition)):
        depth += {'(': 1, ')': -1}.get(definition[i], 0)
        if depth == 0:
            end = i
            break
    if end is None:
        return None
    required = optional = 0
    variadic = False
    for part in definition[start:end].split(','):
        part = part.strip()
        if not part:
            continue
        if part.startswith('..'):
            variadic = True
        elif '=' in part:
            optional += 1
        else:
            required += 1
    return required, None if variadic else required + optional


def call_arities(expr):
    """[(operator, argument count)] for every call in one expression (nested calls included)."""
    text = re.sub(r'/\*.*?\*/', ' ', expr, flags=re.S)
    text = re.sub(r'(#|//)[^\n]*', ' ', text)
    text = re.sub(r'"[^"]*"|\'[^\']*\'', ' ', text)
    out = []
    for m in re.finditer(r'\b([A-Za-z_][A-Za-z0-9_]*)\s*\(', text):
        depth, args, seen = 1, 0, False
        for ch in text[m.end():]:
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
                if depth == 0:
                    break
            if depth == 1 and ch == ',':
                args += 1
            elif not ch.isspace() and not (depth == 1 and ch == ')'):
                seen = True
        if depth == 0:
            out.append((m.group(1), args + 1 if seen else 0))
    return out


def arity_problems(expr, catalog):
    """Blocking problems for calls whose argument count the operator definition does not allow."""
    problems, done = [], set()
    depth = 0
    for ch in re.sub(r'"[^"]*"', ' ', expr):
        depth += {'(': 1, ')': -1}.get(ch, 0)
        if depth < 0:
            break
    if depth != 0:
        return [{'kind': 'unbalanced_parens', 'name': 'parentheses', 'detail': '括號不成對，送出去會是語法錯誤'}]
    for op, n in call_arities(expr):
        bounds = catalog.get('arity', {}).get(op)
        if not bounds or (op, n) in done:
            continue
        done.add((op, n))
        low, high = bounds
        if n < low or (high is not None and n > high):
            want = f'{low}' if high == low else (f'至少 {low}' if high is None else f'{low}–{high}')
            problems.append({'kind': 'wrong_arity', 'name': op,
                             'detail': f'{op} 收 {want} 個參數，表達式給了 {n} 個'})
    return problems


def _pool(template):
    pool = {}
    raw = template.get('gene_pool')
    for key, values in (raw.items() if isinstance(raw, dict) else []):
        values = [str(v) for v in (values if isinstance(values, list) else [values])]
        if values:
            pool[key if key.startswith('<') else f'<{key}>'] = values
    return pool


def _seeds(template):
    return [s.get('expression') for s in template.get('seeds') or []
            if isinstance(s, dict) and isinstance(s.get('expression'), str)]


def expressions(template, notes=None):
    """Filled-in expressions that put every gene-pool value in its real position at least once.
    Gene values are often fragments (`group_<norm>` + `zscore`, `<outer_op>` + `rank`), so they can only
    be checked after substitution. Other placeholders take their first value. Seed files keep their
    expressions in seeds[].expression instead."""
    text = template.get('template')
    if not isinstance(text, str):
        return _seeds(template)
    pool = _pool(template)

    def fill(expr, chosen):
        for _ in range(3):  # gene values may themselves contain placeholders
            for key, values in pool.items():
                expr = expr.replace(key, chosen.get(key, values[0]))
        return expr

    out = [fill(text, {})]
    for key, values in pool.items():
        for value in values[1:]:
            out.append(fill(text, {key: value}))
            if len(out) >= MAX_EXPANSIONS:
                if notes is not None:
                    notes.append(f'gene 組合超過 {MAX_EXPANSIONS} 個，只檢查了前面部分')
                return out + _seeds(template)
    return out + _seeds(template)


def compound_names(template):
    """Identifiers built from two or more placeholders (`anl14_<stat>_<field>_<period>`): every combination."""
    text, pool = template.get('template'), _pool(template)
    if not isinstance(text, str):
        return set()
    names = set()
    for token in re.findall(r'[A-Za-z0-9_]*(?:<[A-Za-z0-9_]+>[A-Za-z0-9_]*){2,}', text):
        parts = [token]
        for key in PLACEHOLDER.findall(token):
            values = pool.get(f'<{key}>')
            if not values:
                break
            parts = [p.replace(f'<{key}>', v, 1) for p in parts for v in values][:MAX_COMPOUND]
        names |= {p for p in parts if '<' not in p}
    return names


def analyse(expr):
    """Return (operators called, candidate field names) for one filled-in FastExpr expression."""
    text = re.sub(r'/\*.*?\*/', ' ', expr, flags=re.S)      # comments
    text = re.sub(r'(#|//)[^\n]*', ' ', text)
    text = re.sub(r'"[^"]*"|\'[^\']*\'', ' ', text)         # string literals
    calls = set(re.findall(r'\b([A-Za-z_][A-Za-z0-9_]*)\s*\(', text))
    # Assigned variables and keyword arguments (`x = ...`, `rate=3`, `filter=true`) are not fields.
    assigned = set(re.findall(r'\b([A-Za-z_][A-Za-z0-9_]*)\s*=(?!=)', text))
    names = set(IDENT.findall(text)) - calls - assigned
    fields = {n for n in names if n.lower() not in CONSTANTS and n.lower() not in GROUPING}
    return calls, fields


def neutralization_genes(template):
    """Gene-pool keys whose values are groupings or neutralization modes (the GA would vary only the neutralization)."""
    modes = GROUPING | {n.lower() for n in PP_NEUTRALIZATIONS} | {'none', 'statistical'}
    return sorted(key for key, values in _pool(template).items()
                  if len(values) >= 2 and all(v.strip().lower() in modes for v in values))


def vector_misuse(expr, vector_fields):
    """VECTOR fields that appear at least once without being the first argument of a vec_* call."""
    bad = set()
    for field in vector_fields:
        used = len(re.findall(rf'\b{re.escape(field)}\b', expr))
        wrapped = len(re.findall(rf'\bvec_[A-Za-z0-9_]*\(\s*{re.escape(field)}\b', expr))
        if used > wrapped:
            bad.add(field)
    return bad


def _result(ok, problems, warnings, fields=0, ops=0, catalog=()):
    return {'ok': ok, 'problems': problems, 'warnings': warnings,
            'checked': {'fields': fields, 'operators': ops, 'catalog': list(catalog)}}




def check(template, setting, data_dir, halted=None):
    """template：{'template': ..., 'gene_pool': {...}} 或 {'seeds': [{'expression': ...}]}。
    setting：{'region','universe','delay','neutralization'}。回 {'ok': True/False/None, 'problems', 'warnings', 'checked'}。"""
    region, universe = setting.get('region'), setting.get('universe')
    delay = setting.get('delay', 1)
    problems, warnings = [], []
    text = template.get('template')
    if isinstance(text, str) and PYTHON.search(text):
        return _result(None, [], ['Python template（@alpha），目前只檢查 FastExpr'])
    catalog = load_catalog(data_dir, region, universe, delay)
    if not catalog['sources'] or not catalog['ops']:
        return _result(None, [], [f'catalog 資料夾沒有 {region}/{universe}/D{delay} 的欄位清單或 operators.json，'
                                  '先跑 catalog_export.py'], catalog=catalog['sources'])
    ops_used, fields_used, unfilled, bare_vectors = set(), set(), set(), set()
    arity_seen = {}
    for expr in expressions(template, warnings):
        unfilled |= set(PLACEHOLDER.findall(expr))
        if not PLACEHOLDER.search(expr):
            for p in arity_problems(expr, catalog):
                arity_seen.setdefault((p['name'], p['detail']), p)
        calls, fields = analyse(PLACEHOLDER.sub(' ', expr))
        ops_used |= calls
        fields_used |= fields
        bare_vectors |= vector_misuse(expr, fields & catalog['vectors'])
    fields_used |= compound_names(template)
    if not ops_used and not fields_used and not unfilled:
        return _result(None, [], warnings + ['找不到可檢查的表達式'], catalog=catalog['sources'])
    for name in sorted(unfilled):
        problems.append({'kind': 'unfilled_placeholder', 'name': f'<{name}>',
                         'detail': 'gene pool 沒有提供值，送出去會是字面上的 <…>'})
    for op in sorted(ops_used - catalog['ops']):
        problems.append({'kind': 'unknown_operator', 'name': op, 'detail': '你帳號的 operators 清單沒有這個 operator'})
    for field in sorted(fields_used - catalog['fields']):
        if field in catalog['removed']:
            problems.append({'kind': 'removed_field', 'name': field, 'detail': f"{catalog['removed'][field]} 匯出時記錄為下架"})
        elif catalog['exact_universe']:
            problems.append({'kind': 'missing_field', 'name': field, 'detail': f'{region}/{universe}/D{delay} 沒有這個欄位'})
        else:
            warnings.append(f'{field}：同 region 已匯出的 universe 都沒有（{universe} 沒匯出，無法確定）')
    problems.extend(arity_seen.values())
    if not catalog['exact_universe']:
        warnings.append(f"{region}/{universe} 沒有匯出，改用 {', '.join(catalog['sources'])} 檢查")
    for field in sorted(bare_vectors):
        problems.append({'kind': 'vector_without_vec_op', 'name': field,
                         'detail': 'VECTOR 欄位沒有先用 vec_* operator（例如 vec_avg）包起來，模擬會直接報錯'})
    for key in neutralization_genes(template):
        warnings.append(f'gene {key} 只是在換分組／neutralization：同一訊號只差中性化方式，產出彼此相關常常很高。'
                        '建議分組固定，gene 放在訊號、窗口、運算子上')
    if halted and str(region or '').upper() in halted:
        warnings.append(f'{region}：{halted[str(region).upper()]}')
    neut = str(setting.get('neutralization') or '').upper()
    if neut in PP_NEUTRALIZATIONS:
        warnings.append(f'neutralization={neut} 屬 Power Pool 家族：產出會帶 PURE_POWER_POOL_THEME，不能走 Regular 繳交')
    return _result(not problems, problems, warnings, len(fields_used), len(ops_used), catalog['sources'])


def check_lines(lines, setting, data_dir, halted=None):
    """一行一個表達式：逐行檢查，回 [(行號, 表達式, 結果)]。"""
    out = []
    for no, line in enumerate(lines, 1):
        expr = line.strip()
        if not expr or expr.startswith('#'):
            continue
        out.append((no, expr, check({'seeds': [{'expression': expr}]}, setting, data_dir, halted)))
    return out


def _print(r):
    for p in r['problems']:
        print(f"  ✗ {p['kind']} {p['name']}：{p['detail']}")
    for w in r['warnings']:
        print(f'  ! {w}')


def main(argv=None):
    ap = argparse.ArgumentParser(description='Alpha 安檢門：送模擬前檢查表達式')
    ap.add_argument('input', help='.txt（一行一個表達式）或 .json（template＋gene_pool，或 seeds）')
    ap.add_argument('--region', required=True)
    ap.add_argument('--universe', required=True)
    ap.add_argument('--delay', type=int, default=1)
    ap.add_argument('--neutralization', default='')
    ap.add_argument('--catalog', default='catalog', help='catalog_export.py 匯出的資料夾')
    ap.add_argument('--config', help='選填：{"halted_regions": {"MEA": "暫停模擬"}}')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    setting = {'region': a.region.upper(), 'universe': a.universe.upper(), 'delay': a.delay,
               'neutralization': a.neutralization}
    conf = _load(a.config) if a.config else None
    halted = {k.upper(): v for k, v in ((conf or {}).get('halted_regions') or {}).items()}
    path = Path(a.input)
    state = {True: 'PASS', False: 'BLOCKED', None: 'UNKNOWN'}
    if path.suffix.lower() == '.json':
        r = check(_load(path) or {}, setting, Path(a.catalog), halted)
        if a.json:
            print(json.dumps(r, ensure_ascii=False, indent=1))
        else:
            c = r['checked']
            print(f"{state[r['ok']]}：檢查了 {c['fields']} 個欄位、{c['operators']} 個運算子"
                  f"（catalog：{', '.join(c['catalog']) or '無'}）")
            _print(r)
        sys.exit({True: 0, False: 1, None: 2}[r['ok']])
    rows = check_lines(path.read_text(encoding='utf-8').splitlines(), setting, Path(a.catalog), halted)
    if a.json:
        print(json.dumps([{'line': n, 'expression': e, **r} for n, e, r in rows], ensure_ascii=False, indent=1))
    else:
        bad = [x for x in rows if x[2]['ok'] is False]
        unk = [x for x in rows if x[2]['ok'] is None]
        print(f'共 {len(rows)} 個表達式：PASS {len(rows) - len(bad) - len(unk)}、BLOCKED {len(bad)}、無法判斷 {len(unk)}')
        for n, e, r in rows:
            if r['ok'] is not True or r['warnings']:
                print(f"第 {n} 行 {state[r['ok']]}：{e[:90]}{'…' if len(e) > 90 else ''}")
                _print(r)
    if any(r['ok'] is False for _, _, r in rows):
        sys.exit(1)
    sys.exit(2 if rows and all(r['ok'] is None for _, _, r in rows) else 0)


if __name__ == '__main__':
    main()
