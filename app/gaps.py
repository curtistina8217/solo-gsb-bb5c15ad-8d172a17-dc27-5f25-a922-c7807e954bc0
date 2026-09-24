"""设备缺口查询：按连续缺口区间计算，支持 limit/offset 分页。

缺口 = 从 next_expected（committed_upto + 1）到缓冲区最大序号之间、
不在缓冲区中的序号。缺口可能极其稀疏（例如先提交 seq=1、再缓冲
seq=100000000 时存在近一亿个缺口），逐个构造会阻塞请求甚至耗尽内存，
因此这里先把有序缓冲序号折叠成若干连续缺口区间，总数与分页都按区间
长度做算术推进：翻到深处时整段跳过被翻过的区间，只展开本页所需序号。
"""

from typing import List, Sequence, Tuple


def gap_intervals(
    committed_upto: int, buffered_seqs: Sequence[int]
) -> List[Tuple[int, int]]:
    """把缺口折叠为连续闭区间列表 [(start, end), ...]，按起点升序。

    buffered_seqs 必须升序；只统计 committed_upto 之后到缓冲区最大序号
    之间的缺口。缓冲区为空时无缺口。
    """
    intervals: List[Tuple[int, int]] = []
    if not buffered_seqs:
        return intervals
    cursor = committed_upto + 1  # next_expected：下一个待处理序号
    for seq in buffered_seqs:
        if seq > cursor:
            intervals.append((cursor, seq - 1))
        cursor = max(cursor, seq + 1)
    return intervals


def paginate_gaps(
    committed_upto: int,
    buffered_seqs: Sequence[int],
    limit: int,
    offset: int,
) -> Tuple[int, List[int]]:
    """返回 (缺口总数, 本页缺口序号)。

    缺口总数按区间长度求和，与分页无关；offset 之前的整段缺口区间按
    长度直接跳过，只展开本页最多 limit 个序号，因此稀疏大缺口与深翻页
    都不会逐个遍历被跳过的缺口。
    """
    intervals = gap_intervals(committed_upto, buffered_seqs)
    total = sum(end - start + 1 for start, end in intervals)
    page: List[int] = []
    remaining_skip = offset
    for start, end in intervals:
        if len(page) >= limit:
            break
        size = end - start + 1
        if remaining_skip >= size:
            remaining_skip -= size
            continue
        first = start + remaining_skip
        remaining_skip = 0
        last = min(end, first + (limit - len(page)) - 1)
        page.extend(range(first, last + 1))
    return total, page
