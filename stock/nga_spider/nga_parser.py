# -*- coding: UTF-8 -*-
"""
NGA 内容解析工具
- 复用原 nga_format.py 的 anony() 匿名转换逻辑
- 提供轻量级 BBCode 剥除（不下载文件，只提取文本和图片URL）
- 提取引用信息（quote_pid、quote_text）
"""
import re
import json
import logging
from typing import Tuple, List, Optional

logger = logging.getLogger(__name__)


# ──────────────────────── 匿名用户名转换（来自 nga_format.py）──────────────
def anony(raw: str) -> str:
    """将 #anony_xxx 匿名标识转为汉字化名"""
    anony_string1 = '甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉戌亥'
    anony_string2 = ('王李张刘陈杨黄吴赵周徐孙马朱胡林郭何高罗郑梁谢宋唐许邓冯韩曹曾彭萧蔡潘田董袁于余叶蒋'
                     '杜苏魏程吕丁沈任姚卢傅钟姜崔谭廖范汪陆金石戴贾韦夏邱方侯邹熊孟秦白江阎薛尹段雷黎史龙'
                     '陶贺顾毛郝龚邵万钱严赖覃洪武莫孔汤向常温康施文牛樊葛邢安齐易乔伍庞颜倪庄聂章鲁岳翟殷'
                     '詹申欧耿关兰焦俞左柳甘祝包宁尚符舒阮柯纪梅童凌毕单季裴霍涂成苗谷盛曲翁冉骆蓝路游辛靳'
                     '管柴蒙鲍华喻祁蒲房滕屈饶解牟艾尤阳时穆农司卓古吉缪简车项连芦麦褚娄窦戚岑景党宫费卜冷'
                     '晏席卫米柏宗瞿桂全佟应臧闵苟邬边卞姬师和仇栾隋商刁沙荣巫寇桑郎甄丛仲虞敖巩明佘池查麻苑迟邝')
    rex = re.findall(r'#anony_.{32}', raw)
    for aname in rex:
        i = 6
        res = ''
        for j in range(6):
            if j == 0 or j == 3:
                if int('0x0' + aname[i + 1], 16) < len(anony_string1):
                    res += anony_string1[int('0x0' + aname[i + 1], 16)]
            else:
                if int('0x' + aname[i:i + 2], 16) < len(anony_string2):
                    res += anony_string2[int('0x' + aname[i:i + 2], 16)]
            i += 2
        res += '?'
        raw = raw.replace(aname, res)
    return raw


# ──────────────────────── 图片 URL 提取 ──────────────────────────────────────
def extract_images(raw: str) -> List[str]:
    """提取帖子内所有图片URL（不下载，只返回原始URL列表）"""
    urls = []
    rex = re.findall(r'\[img\](.+?)\[/img\]', raw, flags=re.I)
    for item in rex:
        url = str(item).strip()
        if url.startswith('./'):
            url = 'https://img.nga.178.com/attachments/' + url[2:]
        # 去掉缩略图后缀
        url = url.replace('.medium.jpg', '')
        urls.append(url)
    return urls


# ──────────────────────── 引用信息提取 ───────────────────────────────────────
def extract_quote(raw: str) -> Tuple[Optional[int], Optional[str]]:
    """
    从原始内容里提取引用的 pid 和引用摘要文本
    返回 (quote_pid, quote_text)，无引用则为 (None, None)
    """
    # 标准引用 [quote][pid=xxx,...][/quote]
    m = re.search(
        r'\[quote\]\[pid=(\d+),.+?\[/b\](.+?)\[/quote\]',
        raw, flags=re.S
    )
    if m:
        pid = int(m.group(1))
        text = strip_bbcode(m.group(2))[:200]  # 最多200字摘要
        return pid, text

    # 引用主帖 [quote][tid=...][/quote]
    m2 = re.search(
        r'\[quote\]\[tid=\d+\].+?\[b\](.+?)\[/b\](.+?)\[/quote\]',
        raw, flags=re.S
    )
    if m2:
        text = strip_bbcode(m2.group(2))[:200]
        return None, text  # 主帖引用没有具体 pid

    return None, None


# ──────────────────────── BBCode 剥除（轻量版） ───────────────────────────────
_BBCODE_TAG_RE = re.compile(r'\[/?[a-zA-Z][^\]]*\]', flags=re.S)
_HTML_TAG_RE   = re.compile(r'<[^>]+>', flags=re.S)

def strip_bbcode(raw: str) -> str:
    """剥除 BBCode 和 HTML 标签，返回纯文本摘要"""
    text = raw or ''
    text = text.replace('<br/>', '\n').replace('<br>', '\n')
    text = _BBCODE_TAG_RE.sub('', text)
    text = _HTML_TAG_RE.sub('', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ──────────────────────── 构造微信推送消息 ────────────────────────────────────
def build_wx_message(tid: int, floor_num: int, pid: int,
                     author_name: str, post_date: str,
                     content_text: str, quote_text: Optional[str],
                     images: List[str], thread_name: str = '') -> str:
    """
    构造适合微信推送的文字消息
    """
    lines = []
    if thread_name:
        lines.append(f'【NGA监控】{thread_name}')
    else:
        lines.append(f'【NGA监控】tid:{tid}')
    lines.append(f'🏠 第 {floor_num} 楼  |  {post_date}')
    lines.append(f'👤 {author_name}')
    lines.append('─' * 20)

    # 引用摘要
    if quote_text:
        short_quote = quote_text[:80] + ('…' if len(quote_text) > 80 else '')
        lines.append(f'↩ 引用：{short_quote}')
        lines.append('')

    # 正文摘要（最多 300 字）
    body = (content_text or '').strip()
    if len(body) > 300:
        body = body[:300] + '…'
    lines.append(body)

    # 图片提示
    if images:
        lines.append('')
        lines.append(f'🖼 含 {len(images)} 张图片')
        # 只附加第一张图片URL，微信不能直接渲染但可以点击
        lines.append(images[0])

    lines.append(f'\nhttps://bbs.nga.cn/read.php?pid={pid}&opt=128')
    return '\n'.join(lines)
