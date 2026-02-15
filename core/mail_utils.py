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


def extract_verification_code(text: str) -> Optional[str]:
    """提取验证码"""
    if not text:
        return None

    # 先去除 HTML，避免匹配到 DOCTYPE 等标签内容
    clean = _strip_html(text)

    # 策略1: 上下文关键词 + 分隔符（冒号 / "is"）+ 候选必须含数字
    # 要求候选码至少包含一个数字，排除 "Your"、"Code" 等英文单词误匹配
    context_pattern = r"(?:验证码|code|verification|passcode|pin).*?(?:[:：]|\bis\b)\s*([A-Za-z0-9]{4,8})\b"
    for m in re.finditer(context_pattern, clean, re.IGNORECASE):
        candidate = m.group(1)
        if re.search(r"\d", candidate) and not re.match(
            r"^\d+(?:px|pt|em|rem|vh|vw|%)$", candidate, re.IGNORECASE
        ):
            return candidate

    # 策略2: 6位大写字母数字混合（至少含一个数字）
    for m in re.finditer(r"[A-Z0-9]{6}", clean):
        candidate = m.group(0)
        if re.search(r"\d", candidate):
            return candidate

    # 策略3: 6位纯数字
    digits = re.findall(r"\b\d{6}\b", clean)
    if digits:
        return digits[0]

    # 策略4: 6位纯大写字母（兜底）
    match = re.search(r"\b[A-Z]{6}\b", clean)
    if match:
        return match.group(0)

    return None
