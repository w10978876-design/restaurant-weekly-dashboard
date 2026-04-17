"""Extract keywords from raw review text: noun+adjective spans from original wording."""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable

# 本地 vendor（pip install -t vendor），便于无全局写权限环境加载 jieba
_VENDOR = Path(__file__).resolve().parent.parent / "vendor"
if _VENDOR.is_dir():
    _vp = str(_VENDOR)
    if _vp not in sys.path:
        sys.path.insert(0, _vp)

# 仅统计与出餐/等候相关的表述，避免「服务太慢」等笼统差评误触发「上菜慢」
_SLOW_PAT = re.compile(
    r"(上菜慢|出餐慢|上菜太慢|出餐太慢|等很久|等太久|等待太久|排队久|排队太久|催单)"
)
_HYGIENE_PAT = re.compile(r"(脏|不卫生|卫生差|异味|臭味|发霉|蟑螂|虫子)")
_SEG = re.compile(r"[，。！？、；：\n\r,\.;!?\|]+")
_NON_TEXT = re.compile(r"\[[^\]]*\]|\([^)]*\)|（[^）]*）|https?://\S+")

# 名词性 / 形容词性（jieba posseg）；an 名形词在评价里常作主题名（如「卫生」）
_NOUN_FLAGS = frozenset({"n", "nr", "ns", "nt", "nz", "vn", "ng", "an"})
# 习语、状态词、名形词作谓语时；nr 常被误标在「安静」等状态词上
_ADJ_LIKE_FLAGS = frozenset({"a", "ad", "an", "l", "z"})
_NR_STATE_WORDS = frozenset(
    {
        "安静",
        "热闹",
        "拥挤",
        "冷清",
        "嘈杂",
        "温馨",
        "舒适",
        "干净",
        "整洁",
        "凌乱",
        "脏乱",
        "乱",
        "挤",
        "吵",
        "静",
    }
)
# jieba 常把「贴心」等标成动词，但语义上是评价补足语（展示词仍来自原文）
_EVAL_VERB_END = frozenset(
    {
        "贴心",
        "用心",
        "负责",
        "仔细",
        "热情",
        "周到",
        "专业",
        "耐心",
        "及时",
        "好吃",
        "难吃",
        "好喝",
        "难喝",
    }
)
# 不与前一名词合并成超长主题（如「服务员态度」），避免吞掉可单独成条的「态度很好」
_SKIP_NOUN_MERGE = frozenset({"有点", "有些", "很多", "不少", "一些", "特别", "非常", "十分", "相当"})
# 程度副词（仅作桥接，不单独成词）
_DEGREE_FLAGS = frozenset({"d", "dg"})
_DEGREE_WORDS = frozenset(
    {
        "很",
        "挺",
        "太",
        "更",
        "还",
        "也",
        "真",
        "蛮",
        "颇",
        "极",
        "巨",
        "超",
        "好",
        "十分",
        "非常",
        "特别",
        "比较",
        "有点",
        "有些",
        "稍微",
        "略",
        "格外",
        "尤其",
        "相当",
        "无比",
        "极其",
        "尤为",
        "真的",
        "确实",
        "多少",
    }
)
_BAD_DEGREE_BRIDGES = frozenset({"都"})
_ALLOW_SINGLE_CHAR_TAIL = frozenset({"慢", "差", "脏", "咸", "淡", "贵", "挤", "吵", "乱"})
_GENERIC_SENSORY_NOUNS = frozenset({"口味", "味道", "口感"})
_BROAD_HEAD_NOUNS = frozenset({"披萨", "出品", "酱香", "奶油味道", "奶油味", "味道", "口感"})
_BAD_NOUN_ANCHORS = frozenset({"口吃"})
_GENERIC_HEADS = frozenset({"环境", "服务", "口味", "味道", "口感", "菜品", "出品"})
_BAD_PHRASE_FRAGMENTS = frozenset({"制造商", "用心良苦"})
_CROWD_PAT = re.compile(r"(太挤|很挤|拥挤|人太多|人很多|排队拥挤)")
_NEG_CUE_PAT = re.compile(r"(差|不好|不行|不佳|很吵|太吵|慢|久|脏|乱|贵|咸|淡|预制菜|包装)")
_POS_CUE_PAT = re.compile(r"(好吃|不错|香|浓郁|舒适|周到|热情|稳定|新鲜|划算|满意)")
_CAUSAL_PATTERNS = [
    re.compile(r"([\u4e00-\u9fff]{2,16}(?:太大|过大|太高|过高|太多|过多|拥挤|太挤|很挤|太吵|很吵).{0,6}?导致[\u4e00-\u9fff]{2,16}(?:很差|较差|变差|不好))"),
    re.compile(r"([\u4e00-\u9fff]{2,16}导致[\u4e00-\u9fff]{2,16}(?:很差|较差|变差|不好))"),
]

_NOUN_BLOCK = frozenset(
    {
        "这个",
        "那个",
        "这里",
        "那里",
        "什么",
        "怎么",
        "这样",
        "那样",
        "我们",
        "你们",
        "他们",
        "自己",
        "大家",
        "时候",
        "今天",
        "下次",
        "整体",
        "感觉",
        "体验",
        "东西",
        "人食",
        "觉得",
        "认为",
        "如果",
        "因为",
        "所以",
        "但是",
        "不过",
        "而且",
    }
)
_NOUN_BRIDGE = frozenset({"体验", "感受"})
_DEGREE_PREFIX = tuple(sorted(_DEGREE_WORDS, key=len, reverse=True))
_LEADING_NOISE = ("其是", "其实", "了")

_jieba_pseg = None


def _get_pseg():
    global _jieba_pseg
    if _jieba_pseg is None:
        import jieba.posseg as pseg  # type: ignore

        _jieba_pseg = pseg
    return _jieba_pseg


def _normalize_text(t: str) -> str:
    s = str(t or "")
    s = _NON_TEXT.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _split_clauses(text: str) -> list[str]:
    s = _normalize_text(text)
    if not s:
        return []
    return [x.strip(" .!?,;，。！？、；：") for x in _SEG.split(s) if x.strip(" .!?,;，。！？、；：")]


def _tokenize_with_spans(clause: str) -> list[tuple[str, str, int, int]]:
    """返回 (词, 词性, start, end)，基于 clause 内下标。"""
    pseg = _get_pseg()
    out: list[tuple[str, str, int, int]] = []
    pos = 0
    for pair in pseg.cut(clause):
        w = str(getattr(pair, "word", pair)).strip()
        if not w:
            continue
        flag = str(getattr(pair, "flag", ""))
        idx = clause.find(w, pos)
        if idx < 0:
            idx = clause.find(w)
        if idx < 0:
            continue
        end = idx + len(w)
        out.append((w, flag, idx, end))
        pos = end
    return out


def _is_noun_token(flag: str) -> bool:
    return flag in _NOUN_FLAGS


def _is_adj_token(flag: str) -> bool:
    return flag in _ADJ_LIKE_FLAGS


def _is_phrase_end(w: str, flag: str) -> bool:
    if _is_adj_token(flag):
        return True
    if flag == "nr" and w in _NR_STATE_WORDS:
        return True
    if flag in frozenset({"v", "vi", "vn"}) and w in _EVAL_VERB_END:
        return True
    return False


def _is_degree_bridge(w: str, flag: str) -> bool:
    if w in _BAD_DEGREE_BRIDGES:
        return False
    if w in _DEGREE_WORDS:
        return True
    return False


def _is_high_quality_phrase(phrase: str) -> bool:
    if not phrase:
        return False
    # 低信息或病句式尾词，直接过滤
    if len(phrase) >= 1 and phrase[-1] in {"累", "小", "高"}:
        return False
    if any(x in phrase for x in _BAD_PHRASE_FRAGMENTS):
        return False
    if phrase.startswith("口吃") or "第一口吃" in phrase:
        return False
    if phrase.startswith("一遇的") or phrase.startswith("遇的"):
        return False
    toks = _tokenize_with_spans(phrase)
    if len(toks) < 2:
        return False
    last_word, _, _, _ = toks[-1]
    if len(last_word) == 1 and last_word not in _ALLOW_SINGLE_CHAR_TAIL:
        return False
    return True


def _phrase_quality_boost(phrase: str, *, positive_side: bool) -> float:
    """
    提炼排序质量分：
    - 优先具体对象（多词、前缀非泛词）
    - 差评优先因果表达（导致/因为）
    """
    p = str(phrase or "")
    toks = _tokenize_with_spans(p)
    if not toks:
        return 0.0
    boost = 0.0
    first_word = toks[0][0]
    # 具体对象倾向：非泛头词 + 更完整词组
    if first_word not in _GENERIC_HEADS:
        boost += 0.2
    if len(toks) >= 3:
        boost += 0.15
    if len(p) >= 8:
        boost += 0.15
    # 差评优先“原因->结果”
    if not positive_side and ("导致" in p or "因为" in p):
        boost += 0.35
    # 泛词惩罚
    if first_word in _GENERIC_HEADS and len(p) <= 6:
        boost -= 0.25
    return boost


def _expand_generic_head(seg: str, toks: list[tuple[str, str, int, int]], i: int, ek: int) -> str | None:
    """
    若锚点是「口味/味道/口感」，尝试把前置菜品名并入（如「薄饼味道还不错」）。
    补不出来则返回 None（避免「味道还不错」这类无对象短语）。
    """
    w0, _, s0, _ = toks[i]
    if w0 not in _GENERIC_SENSORY_NOUNS:
        return seg[s0:ek]
    for j in range(i - 1, max(-1, i - 4), -1):
        wj, fj, sj, ej = toks[j]
        if not _is_noun_token(fj):
            continue
        if wj in _NOUN_BLOCK or wj in _GENERIC_SENSORY_NOUNS or len(wj) < 2:
            continue
        # 相邻或近邻（中间只允许程度词/助词）
        ok = True
        for k in range(j + 1, i):
            wk, fk, _, _ = toks[k]
            if wk == "的" and fk == "uj":
                continue
            if _is_degree_bridge(wk, fk):
                continue
            if wk in {"和", "与", "及", "、"}:
                continue
            ok = False
            break
        if ok:
            return seg[sj:ek]
    return None


def _expand_broad_head(seg: str, toks: list[tuple[str, str, int, int]], i: int, ek: int, base_phrase: str) -> str | None:
    """
    对「披萨太好吃 / 出品稳定 / 酱香浓郁」这类宽泛主语进行左侧补全；
    若同句找不到具体主语，则返回 None（不展示半截词）。
    """
    w0, _, s0, _ = toks[i]
    if w0 not in _BROAD_HEAD_NOUNS:
        return base_phrase
    # 同句向左找最近的具体名词（如 金枪鱼/酱肘子/奶油培根面）
    for j in range(i - 1, max(-1, i - 5), -1):
        wj, fj, sj, ej = toks[j]
        if not _is_noun_token(fj):
            continue
        if wj in _NOUN_BLOCK or wj in _GENERIC_SENSORY_NOUNS or wj in _BROAD_HEAD_NOUNS or len(wj) < 2:
            continue
        # 中间只允许轻连接词
        ok = True
        for k in range(j + 1, i):
            wk, fk, _, _ = toks[k]
            if wk == "的" and fk == "uj":
                continue
            if _is_degree_bridge(wk, fk):
                continue
            if wk in {"和", "与", "及", "、"}:
                continue
            ok = False
            break
        if ok:
            return seg[sj:ek]
    # 回退：允许夹杂引号等符号，从短语左侧最近中文词回补主语
    pos = seg.find(base_phrase)
    if pos > 0:
        left = seg[:pos]
        m = re.search(r"([\u4e00-\u9fff]{2,10})[^\u4e00-\u9fff]*$", left)
        if m:
            head = m.group(1)
            if head not in _NOUN_BLOCK and head not in _GENERIC_SENSORY_NOUNS and head not in _BROAD_HEAD_NOUNS:
                return f"{head}{base_phrase}"
    return None


def _strip_leading_noise(phrase: str) -> str:
    p = str(phrase or "")
    changed = True
    while changed and p:
        changed = False
        for noise in _LEADING_NOISE:
            if p.startswith(noise) and len(p) > len(noise) + 1:
                p = p[len(noise) :]
                changed = True
                break
    return p


def _normalize_causal_phrase(p: str) -> str:
    s = str(p or "")
    s = re.sub(r"^客单价不低的情况下的", "", s)
    s = re.sub(r"^在[^，。；,;]{0,10}情况下的", "", s)
    s = s.replace("餐桌的密度", "餐桌密度").replace("高密度", "密度过高")
    s = s.replace("太大了", "太大")
    return s


def _is_valid_phrase_start(phrase: str) -> bool:
    toks = _tokenize_with_spans(phrase)
    if not toks:
        return False
    w0, f0, _, _ = toks[0]
    if not _is_noun_token(f0):
        return False
    if w0 in _BAD_NOUN_ANCHORS:
        return False
    if w0 in _NOUN_BLOCK or w0 in _DEGREE_WORDS:
        return False
    if len(w0) < 2:
        return False
    return True


def _extract_phrases(text: str) -> list[str]:
    """从原文分句后，用语义标注取「名词（可连用）+（的/程度）* + 形容词」的连续子串，字面来自用户原文。"""
    s = _normalize_text(text)
    if not s:
        return []
    found: list[str] = []
    for seg in _SEG.split(s):
        seg = seg.strip(" .!?,;，。！？、；：")
        if len(seg) < 2:
            continue
        # 因果短语优先：保留“原因+结果”，避免只剩“用餐体验差”
        for cp in _CAUSAL_PATTERNS:
            for m in cp.finditer(seg):
                p = re.sub(r"\s+", "", _normalize_causal_phrase(_strip_leading_noise(m.group(1))))
                if 4 <= len(p) <= 28:
                    found.append(p)
        toks = _tokenize_with_spans(seg)
        if len(toks) < 2:
            continue
        n = len(toks)
        for i in range(n):
            w0, f0, s0, e0 = toks[i]
            # 阻断「十分难吃」这类无主题短语：程度词/代词/量词不作为名词锚点
            if (
                not _is_noun_token(f0)
                or w0 in _NOUN_BLOCK
                or w0 in _DEGREE_WORDS
                or f0 in {"m", "mq", "q", "r"}
                or len(w0) < 2
            ):
                continue
            # 合并连续名词为一名词短语
            j = i + 1
            e_noun = e0
            while j < n and _is_noun_token(toks[j][1]) and toks[j][0] not in _NOUN_BLOCK:
                if toks[j][0] in _SKIP_NOUN_MERGE:
                    break
                if len(w0) >= 3:
                    break
                e_noun = toks[j][3]
                j += 1
            k = j
            while k < n and k - i <= 8:
                wk, fk, sk, ek = toks[k]
                if _is_noun_token(fk) and wk in _NOUN_BRIDGE:
                    k += 1
                    continue
                # 分词噪声：如「奶油味」「道」「浓郁」中的单字量词“道”
                if wk == "道" and fk in {"q", "mq"}:
                    k += 1
                    continue
                if wk == "的" and fk == "uj":
                    k += 1
                    continue
                if _is_degree_bridge(wk, fk):
                    k += 1
                    continue
                if _is_phrase_end(wk, fk):
                    start = s0
                    # 数量词前缀回补：如「两人食正好」避免截成「人食正好」
                    if (
                        w0.endswith("人食")
                        and start > 0
                        and seg[start - 1] in "一二两三四五六七八九十"
                    ):
                        start -= 1
                    phrase_raw = _expand_generic_head(seg, toks, i, ek)
                    if not phrase_raw:
                        break
                    phrase_raw = _expand_broad_head(seg, toks, i, ek, phrase_raw)
                    if not phrase_raw:
                        break
                    phrase = _strip_leading_noise(phrase_raw)
                    if "服务态度" in phrase and not phrase.startswith("服务态度"):
                        phrase = phrase[phrase.find("服务态度") :]
                    phrase = re.sub(r"\s+", "", phrase)
                    if (
                        2 <= len(phrase) <= 24
                        and _is_valid_phrase_start(phrase)
                        and _is_high_quality_phrase(phrase)
                    ):
                        found.append(phrase)
                    break
                # 非桥接、非补足语则停止该名词锚点（不再向后扫）
                break
    # 同一条评价里，若短串被长串完整包含，只保留长串（仍是原文子串）
    if len(found) > 1:
        found.sort(key=len, reverse=True)
        pruned: list[str] = []
        for x in found:
            if any(x != y and x in y for y in pruned):
                continue
            pruned.append(x)
        found = pruned
    uniq: list[str] = []
    seen: set[str] = set()
    for x in found:
        if x in seen:
            continue
        seen.add(x)
        uniq.append(x)
    return uniq


def _extract_suspect_phrases(text: str) -> list[str]:
    """提取需要补全的残缺候选，如「十分难吃」「餐体验差」「子披萨好吃」."""
    s = _normalize_text(text)
    if not s:
        return []
    out: list[str] = []
    for seg in _SEG.split(s):
        seg = seg.strip(" .!?,;，。！？、；：")
        if len(seg) < 2:
            continue
        toks = _tokenize_with_spans(seg)
        if len(toks) < 2:
            continue
        n = len(toks)
        for i in range(n - 1):
            w0, f0, s0, e0 = toks[i]
            w1, f1, s1, e1 = toks[i + 1]
            # 程度词 + 评价结尾：如「十分难吃」
            if _is_degree_bridge(w0, f0) and _is_phrase_end(w1, f1):
                out.append(seg[s0:e1])
            # 单字名词 + 名词桥接 + 评价结尾：如「餐体验差」「子披萨好吃」
            if len(w0) == 1 and _is_noun_token(f0) and i + 2 < n:
                w2, f2, s2, e2 = toks[i + 2]
                if _is_noun_token(f1) and _is_phrase_end(w2, f2):
                    out.append(seg[s0:e2])
    uniq: list[str] = []
    seen: set[str] = set()
    for x in out:
        if x in seen:
            continue
        seen.add(x)
        uniq.append(x)
    return uniq


def _append_evidence(evidence: dict[str, list[str]], phrase: str, sentence: str) -> None:
    if not phrase or not sentence:
        return
    arr = evidence.setdefault(phrase, [])
    if sentence in arr:
        return
    if len(arr) >= 2:
        return
    arr.append(sentence)


def _find_evidence_sentence(text: str, phrase: str) -> str | None:
    p = re.sub(r"\s+", "", str(phrase or ""))
    if not p:
        return None
    for seg in _split_clauses(text):
        seg_norm = re.sub(r"\s+", "", seg)
        if p in seg_norm:
            return seg
    return None


def _repair_suspect_phrase(phrase: str, corpus_texts: list[str]) -> str | None:
    """在同批原文中回溯补全残缺词条，找不到则丢弃（不降级）。"""
    p = re.sub(r"\s+", "", str(phrase or ""))
    if len(p) < 2:
        return None
    normalized_corpus = [_normalize_text(t).replace(" ", "") for t in corpus_texts if str(t or "").strip()]
    if not normalized_corpus:
        return None

    pat = None
    # 1) 程度词开头：补前置主题，如「披萨十分难吃」
    if any(p.startswith(dw) for dw in _DEGREE_PREFIX):
        # 「很好/不错」这类过短评价无法稳定回补主题，避免误拼接背景名词
        if len(p) < 4:
            return None
        pat = re.compile(rf"([\u4e00-\u9fff]{{1,6}}{re.escape(p)})")
    # 2) 单字开头：补更完整主题，如「榴莲披萨好吃」「用餐体验差」
    elif len(p) >= 3 and re.match(r"[\u4e00-\u9fff]", p[0]):
        tail = p[1:]
        pat = re.compile(rf"([\u4e00-\u9fff]{{1,6}}{re.escape(tail)})")

    if pat is None:
        return None

    cands: Counter[str] = Counter()
    for txt in normalized_corpus:
        for m in pat.finditer(txt):
            cand = m.group(1)
            cand = _strip_leading_noise(cand)
            if not (2 <= len(cand) <= 24):
                continue
            if cand == p:
                continue
            if any(cand.startswith(dw) for dw in _DEGREE_PREFIX):
                continue
            if "的" in cand[:4]:
                continue
            if not _is_valid_phrase_start(cand) or not _is_high_quality_phrase(cand):
                continue
            cands[cand] += 1
    if not cands:
        return None
    return cands.most_common(1)[0][0]


def _collect_phrases_and_evidence(
    texts: Iterable[str], include_crowd_issue: bool = False
) -> tuple[Counter[str], dict[str, list[str]]]:
    # 固定排序，确保同一份输入得到稳定结果
    text_list = sorted(str(t or "") for t in texts if str(t or "").strip())
    c: Counter[str] = Counter()
    evidence: dict[str, list[str]] = {}
    for t in text_list:
        seen: set[str] = set()
        for p in _extract_phrases(str(t or "")):
            if p in seen:
                continue
            seen.add(p)
            c[p] += 1
            sent = _find_evidence_sentence(t, p) or _normalize_text(t)
            _append_evidence(evidence, p, sent)
        # 负向拥挤问题补充：可无主题直接上榜（仅差评池启用）
        if include_crowd_issue and _CROWD_PAT.search(str(t or "")) and "太挤" not in seen:
            seen.add("太挤")
            c["太挤"] += 1
            sent = _find_evidence_sentence(t, "太挤") or _normalize_text(t)
            _append_evidence(evidence, "太挤", sent)
        # 对残缺候选做“回溯补全”，找不到完整词条则不计入
        for sp in _extract_suspect_phrases(str(t or "")):
            fixed = _repair_suspect_phrase(sp, text_list)
            if not fixed or fixed in seen:
                continue
            seen.add(fixed)
            c[fixed] += 1
            sent = _find_evidence_sentence(t, fixed)
            if sent is None:
                for t2 in text_list:
                    sent = _find_evidence_sentence(t2, fixed)
                    if sent:
                        break
            _append_evidence(evidence, fixed, sent or fixed)
    return c, evidence


def _fallback_from_pool(texts: list[str], *, negative: bool) -> tuple[Counter[str], dict[str, list[str]]]:
    """
    兜底提炼：当结构化提炼失败时，直接从原文分句中抓取带情绪线索的短句，
    保证“池子非空 -> 关键词非空”。
    """
    cue = _NEG_CUE_PAT if negative else _POS_CUE_PAT
    c: Counter[str] = Counter()
    evidence: dict[str, list[str]] = {}

    def _normalize_fallback(seg: str) -> str:
        s = re.sub(r"\s+", "", seg)
        # 常见无效前缀/口头语
        s = re.sub(r"^(但是|不过|但|就是|其实|然后|主要是)+", "", s)
        # 语义化：按“对象+问题状态/动作”动态组合，不使用固定兜底词
        if "预制菜" in s:
            if "包装" in s and ("上餐桌" in s or "上餐" in s):
                return "预制菜上餐仍带包装"
            if "包装" in s and "剪" in s:
                return "预制菜包装处理不规范"
            if "加热" in s and ("包装" in s or "连同" in s):
                return "预制菜加热流程存在包装残留"
            if "不好吃" in s or "难吃" in s:
                return "预制菜口感不佳"
            return "预制菜体验存在问题"
        if "包装" in s and ("上餐" in s or "加热" in s or "餐桌" in s):
            return "上餐流程存在包装处理问题"
        if "太吵" in s or "很吵" in s or "嘈杂" in s:
            return "就餐环境嘈杂"
        if "排队" in s and ("久" in s or "很久" in s or "太久" in s):
            return "排队等待时间过长"
        # 默认截取前半句，避免把整段口语照搬成关键词
        cut = re.split(r"[，。；,;]", s)[0]
        return cut[:18] if len(cut) > 18 else cut

    def _fallback_specificity(key: str) -> int:
        k = str(key or "")
        score = 0
        if "预制菜" in k:
            score += 2
        if "包装" in k:
            score += 3
        if "上餐" in k or "餐桌" in k:
            score += 2
        if "加热" in k:
            score += 2
        if "流程" in k or "处理" in k:
            score += 1
        if "体验存在问题" in k:
            score -= 2
        return score
    for t in sorted(texts):
        has_prepared_food_topic = "预制菜" in re.sub(r"\s+", "", t)
        best_key = None
        best_seg = None
        best_score = -10**9
        for seg in _split_clauses(t):
            s = re.sub(r"\s+", "", seg)
            if len(s) < 4 or len(s) > 120:
                continue
            if not cue.search(s):
                continue
            key = _normalize_fallback(seg)
            if len(key) < 4:
                continue
            sc = _fallback_specificity(key)
            if sc > best_score:
                best_score = sc
                best_key = key
                best_seg = seg
        if best_key:
            # 跨句主题承接：前句出现“预制菜”，后句出现包装/上餐问题时，回补主语
            if has_prepared_food_topic and best_key == "上餐流程存在包装处理问题":
                best_key = "预制菜上餐仍带包装"
            c[best_key] += 1
            _append_evidence(evidence, best_key, best_seg or best_key)
    return c, evidence


def _rank_keywords(
    counter_self: Counter[str],
    counter_other: Counter[str],
    total_reviews_self: int,
    total_reviews_other: int,
    n: int,
) -> list[str]:
    scored: list[tuple[float, str, int]] = []
    for k, tf in counter_self.items():
        if len(k) < 3 and k != "太挤":
            continue
        self_ratio = tf / max(total_reviews_self, 1)
        other_tf = counter_other.get(k, 0)
        other_ratio = other_tf / max(total_reviews_other, 1)
        lift = max(self_ratio - other_ratio, 0.0)
        score = tf * (1.0 + 2.5 * lift + (0.5 if other_tf == 0 else 0.0))
        scored.append((score, k, tf))
    scored.sort(key=lambda x: (-x[0], -x[2], x[1]))
    return [f"{k}（{tf}次）" for _, k, tf in scored[:n]]


def _rank_keywords_detail(
    counter_self: Counter[str],
    counter_other: Counter[str],
    total_reviews_self: int,
    total_reviews_other: int,
    positive_side: bool,
) -> list[dict]:
    ranked: list[dict] = []
    for k, tf in counter_self.items():
        if len(k) < 3 and k != "太挤":
            continue
        self_ratio = tf / max(total_reviews_self, 1)
        other_tf = counter_other.get(k, 0)
        other_ratio = other_tf / max(total_reviews_other, 1)
        lift = max(self_ratio - other_ratio, 0.0)
        score = tf * (1.0 + 2.5 * lift + (0.5 if other_tf == 0 else 0.0))
        score += _phrase_quality_boost(k, positive_side=positive_side)
        ranked.append(
            {
                "keyword": k,
                "count": int(tf),
                "score": round(float(score), 6),
                "selfRatio": round(float(self_ratio), 6),
                "otherCount": int(other_tf),
                "otherRatio": round(float(other_ratio), 6),
                "lift": round(float(lift), 6),
            }
        )
    ranked.sort(key=lambda x: (-x["score"], -x["count"], x["keyword"]))
    for idx, item in enumerate(ranked):
        item["rank"] = idx + 1
    return ranked


def extract_keywords_with_meta(
    texts_good: Iterable[str], texts_bad: Iterable[str], texts_all_for_bad_signals: Iterable[str] | None = None
) -> dict:
    good_texts = [str(t or "") for t in texts_good if str(t or "").strip()]
    bad_texts = [str(t or "") for t in texts_bad if str(t or "").strip()]
    all_texts = (
        [str(t or "") for t in texts_all_for_bad_signals if str(t or "").strip()]
        if texts_all_for_bad_signals is not None
        else (good_texts + bad_texts)
    )

    good_counter, good_evidence = _collect_phrases_and_evidence(good_texts, include_crowd_issue=False)
    bad_counter, bad_evidence = _collect_phrases_and_evidence(bad_texts, include_crowd_issue=True)

    # 兜底：池子有文本但提炼为空时，用句子级关键词保证不为空
    if good_texts and not good_counter:
        fc, fe = _fallback_from_pool(good_texts, negative=False)
        good_counter.update(fc)
        for k, v in fe.items():
            for s in v:
                _append_evidence(good_evidence, k, s)
    if bad_texts and not bad_counter:
        fc, fe = _fallback_from_pool(bad_texts, negative=True)
        bad_counter.update(fc)
        for k, v in fe.items():
            for s in v:
                _append_evidence(bad_evidence, k, s)

    good_ranked = _rank_keywords_detail(good_counter, bad_counter, len(good_texts), len(bad_texts), positive_side=True)
    bad_ranked = _rank_keywords_detail(bad_counter, good_counter, len(bad_texts), len(good_texts), positive_side=False)
    good_kw = [f"{x['keyword']}（{x['count']}次）" for x in good_ranked[:3]]
    bad_kw = [f"{x['keyword']}（{x['count']}次）" for x in bad_ranked[:5]]

    slow_bad_hits = sum(1 for t in bad_texts if _SLOW_PAT.search(t))
    if bad_texts and (slow_bad_hits / len(bad_texts)) > 0.10:
        forced = f"上菜慢（{slow_bad_hits}次）"
        bad_kw = [x for x in bad_kw if not x.startswith("上菜慢（")]
        bad_kw.insert(0, forced)

    hygiene_hits = set()
    for t in bad_texts:
        hygiene_hits.update(_HYGIENE_PAT.findall(t))
    if hygiene_hits:
        badge = f"{'/'.join(sorted(hygiene_hits))}（强预警）"
        bad_kw = [x for x in bad_kw if not x.endswith("（强预警）")]
        bad_kw.insert(0, badge)

    return {
        "goodKeywords": good_kw[:3],
        "badKeywords": bad_kw[:3],
        "goodCounter": good_counter,
        "badCounter": bad_counter,
        "goodEvidence": {k: v[:2] for k, v in good_evidence.items()},
        "badEvidence": {k: v[:2] for k, v in bad_evidence.items()},
        "goodCandidates": good_ranked,
        "badCandidates": bad_ranked,
        "goodReviewCount": len(good_texts),
        "badReviewCount": len(bad_texts),
        "allReviewCountForBadSignals": len(all_texts),
    }


def extract_keywords(
    texts_good: Iterable[str],
    texts_bad: Iterable[str],
    all_texts_for_ratio: list[str],  # reserved for backward compatibility
) -> tuple[list[str], list[str]]:
    meta = extract_keywords_with_meta(texts_good, texts_bad, all_texts_for_ratio)
    return meta["goodKeywords"], meta["badKeywords"]
