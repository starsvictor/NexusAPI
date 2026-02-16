import re
from html import unescape
from typing import Optional


def _strip_html(text: str) -> str:
    """去除 HTML 标签、style/script 块，保留纯文本"""
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _remove_emails(text: str) -> str:
    """移除文本中的邮箱地址，防止邮箱中的数字/字母被误匹配为验证码"""
    return re.sub(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", " ", text)


# 常见英文单词黑名单（全大写时可能被误判为验证码）
_WORD_BLACKLIST = {
    "YOUR", "CODE", "THIS", "THAT", "WITH", "FROM", "HAVE", "BEEN",
    "WILL", "DOES", "DONT", "HERE", "THEM", "THEN", "THAN", "WHEN",
    "WHAT", "SOME", "ONLY", "JUST", "ALSO", "INTO", "OVER", "EACH",
    "SIGN", "LINK", "CLICK", "EMAIL", "VERIFY", "ACCOUNT", "GOOGLE",
}


def extract_verification_code(text: str) -> Optional[str]:
    """提取验证码"""
    if not text:
        return None

    # 先去除 HTML，避免匹配到 DOCTYPE 等标签内容
    clean = _strip_html(text)
    # 移除邮箱地址，防止地址中的数字/字母片段被误匹配
    clean_no_email = _remove_emails(clean)

    # 策略1: 上下文关键词 + 分隔符（冒号 / "is"）+ 候选码
    # 允许纯数字和纯字母验证码（如 Google 的 WXUZMG），排除常见英文单词
    context_pattern = r"(?:验证码|code|verification|passcode|pin).*?(?:[:：]|\bis\b)\s*([A-Za-z0-9]{4,8})\b"
    for m in re.finditer(context_pattern, clean_no_email, re.IGNORECASE):
        candidate = m.group(1)
        # 排除 CSS 单位
        if re.match(r"^\d+(?:px|pt|em|rem|vh|vw|%)$", candidate, re.IGNORECASE):
            continue
        # 排除常见英文单词
        if candidate.upper() in _WORD_BLACKLIST:
            continue
        return candidate

    # 策略2: 6位大写字母数字混合（至少含一个数字）
    for m in re.finditer(r"[A-Z0-9]{6}", clean_no_email):
        candidate = m.group(0)
        if re.search(r"\d", candidate):
            return candidate

    # 策略3: 6位纯大写字母（优先于纯数字，因为验证码常用大写字母）
    match = re.search(r"\b[A-Z]{6}\b", clean_no_email)
    if match and match.group(0) not in _WORD_BLACKLIST:
        return match.group(0)

    # 策略4: 6位纯数字（最后匹配，降低邮箱地址残留误匹配风险）
    digits = re.findall(r"\b\d{6}\b", clean_no_email)
    if digits:
        return digits[0]

    return None
