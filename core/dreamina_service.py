"""
Dreamina 图片生成服务

基于 dreamina2api 参考项目，调用 Dreamina 海外站 API 生成图片。
使用 sessionid cookie 认证，支持多账户 round-robin 轮询。
"""

import asyncio
import hashlib
import json
import logging
import math
import random
import time
import uuid
from typing import Any, Dict, List, Optional

import httpx
from fastapi import HTTPException

from core.storage import load_dreamina_accounts_sync

logger = logging.getLogger("dreamina.service")

# ==================== API 常量（参考 dreamina2api） ====================

API_BASE_URL = "https://dreamina-api.us.capcut.com"
COMMERCE_API_URL = "https://commerce.us.capcut.com"
DEFAULT_ASSISTANT_ID = "513641"
PLATFORM_CODE = "7"
VERSION_CODE = "8.4.0"
APP_SDK_VERSION = "48.0.0"
WEB_VERSION = "7.5.0"
DA_VERSION = "3.3.9"
DRAFT_VERSION = "3.3.9"

# 默认模型
DEFAULT_IMAGE_MODEL = "high_aes_general_v40l"

# 模型映射
IMAGE_MODEL_MAP = {
    "dreamina-4.5": "high_aes_general_v40l",
    "dreamina-4.1": "high_aes_general_v41",
    "dreamina-4.0": "high_aes_general_v40",
    "dreamina-3.1": "high_aes_general_v30l_art_fangzhou:general_v3.0_18b",
    "dreamina-3.0": "high_aes_general_v30l:general_v3.0_18b",
    "dreamina-2.1": "high_aes_general_v21_L:general_v2.1_L",
    "dreamina-2.0-pro": "high_aes_general_v20_L:general_v2.0_L",
    "dreamina-2.0": "high_aes_general_v20:general_v2.0",
    "nano-banana": "external_model_gemini_flash_image_v25",
}

# 状态码
STATUS_PROCESSING = 20
STATUS_SUCCESS = 10
STATUS_FAILED = 30
STATUS_COMPLETED = 50

# 轮询配置
POLL_INTERVAL_SECONDS = 1
POLL_MAX_COUNT = 300  # 最多轮询 300 次（约 5 分钟）

# 伪装 headers
FAKE_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Cache-Control": "no-cache",
    "Content-Type": "application/json",
    "App-Sdk-Version": APP_SDK_VERSION,
    "Appid": DEFAULT_ASSISTANT_ID,
    "Appvr": VERSION_CODE,
    "Origin": "https://dreamina.capcut.com",
    "Pragma": "no-cache",
    "Pf": PLATFORM_CODE,
    "Lan": "en",
    "Loc": "US",
    "Store-Country-Code": "us",
    "Store-Country-Code-Src": "uid",
    "Referer": "https://dreamina.capcut.com/",
    "Sec-Ch-Ua": '"Not(A:Brand";v="8", "Chromium";v="144"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"
    ),
}


# ==================== 工具函数 ====================


def _uuid() -> str:
    return str(uuid.uuid4())


def _unix_ts() -> int:
    return int(time.time())


def _sign(uri: str) -> str:
    """计算请求签名: md5("9e2c|<uri后7位>|<platform>|<version>|<timestamp>||11ac")"""
    device_time = _unix_ts()
    raw = f"9e2c|{uri[-7:]}|{PLATFORM_CODE}|{VERSION_CODE}|{device_time}||11ac"
    return hashlib.md5(raw.encode()).hexdigest(), device_time


def _generate_cookie(session_id: str) -> str:
    """生成海外站 cookie"""
    ts = _unix_ts()
    uid = _uuid().replace("-", "")
    return "; ".join([
        "store-idc=useast5",
        "store-country-code=us",
        "store-country-code-src=uid",
        "cc-target-idc=useast5",
        f"sid_guard={session_id}%7C{ts}%7C5184000%7CFri",
        f"uid_tt={uid}",
        f"uid_tt_ss={uid}",
        f"sid_tt={session_id}",
        f"sessionid={session_id}",
        f"sessionid_ss={session_id}",
    ])


def _get_image_ratio(width: int, height: int) -> int:
    """根据宽高比计算 image_ratio 参数"""
    r = width / height
    if abs(r - 1) < 0.1:
        return 1       # 1:1
    if abs(r - 4 / 3) < 0.1:
        return 4       # 4:3
    if abs(r - 3 / 4) < 0.1:
        return 2       # 3:4
    if abs(r - 16 / 9) < 0.1:
        return 3       # 16:9
    if abs(r - 9 / 16) < 0.1:
        return 5       # 9:16
    if abs(r - 3 / 2) < 0.1:
        return 7       # 3:2
    if abs(r - 2 / 3) < 0.1:
        return 6       # 2:3
    return 1  # 默认正方形


def _parse_size(size: str) -> tuple:
    """解析尺寸字符串，如 '1024x1024' -> (1024, 1024)"""
    if "x" in size:
        parts = size.split("x")
        try:
            return int(parts[0]), int(parts[1])
        except ValueError:
            pass
    return 2048, 2048


# aspect_ratio 字符串 → (宽比, 高比) 映射
_ASPECT_RATIO_MAP = {
    "1:1": (1, 1),
    "16:9": (16, 9),
    "9:16": (9, 16),
    "4:3": (4, 3),
    "3:4": (3, 4),
    "3:2": (3, 2),
    "2:3": (2, 3),
}

# resolution 字符串 → 最长边像素
_RESOLUTION_MAP = {
    "1k": 1024,
    "1K": 1024,
    "2k": 2048,
    "2K": 2048,
    "4k": 4096,
    "4K": 4096,
}


def _compute_size_from_params(
    aspect_ratio: Optional[str] = None,
    resolution: Optional[str] = None,
    default_size: str = "2048x2048",
) -> str:
    """根据 aspect_ratio 和 resolution 计算 size 字符串。

    - aspect_ratio: 如 "16:9", "1:1", "4:3" 等
    - resolution: 如 "1K", "2K"
    - 任何参数缺失时使用 default_size
    """
    if not aspect_ratio and not resolution:
        return default_size

    # 解析最长边
    max_side = _RESOLUTION_MAP.get(resolution, 2048) if resolution else 2048

    # 解析宽高比
    ratio = _ASPECT_RATIO_MAP.get(aspect_ratio)
    if not ratio:
        # 尝试解析自定义比例 "W:H"
        if aspect_ratio and ":" in aspect_ratio:
            try:
                rw, rh = aspect_ratio.split(":")
                ratio = (int(rw), int(rh))
            except (ValueError, ZeroDivisionError):
                ratio = (1, 1)
        else:
            ratio = (1, 1)

    rw, rh = ratio
    if rw >= rh:
        width = max_side
        height = int(max_side * rh / rw)
    else:
        height = max_side
        width = int(max_side * rw / rh)

    # 对齐到 8 像素（图片生成常见要求）
    width = (width // 8) * 8
    height = (height // 8) * 8

    return f"{width}x{height}"


# ==================== 服务类 ====================


class DreaminaService:
    """Dreamina 图片生成服务"""

    def __init__(self, proxy: str = "") -> None:
        self._accounts: List[Dict] = []
        self._index = 0
        self._lock = asyncio.Lock()
        self._device_id = str(random.randint(7000000000000000000, 7999999999999999999))
        self._http = httpx.AsyncClient(
            proxy=proxy or None,
            verify=False,
            timeout=httpx.Timeout(60.0, connect=15.0),
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
        )

    # ==================== 账户管理 ====================

    async def initialize(self) -> None:
        await self.reload_accounts()
        n = len(self._accounts)
        if n > 0:
            logger.info(f"[DREAMINA] 服务已初始化，可用账户: {n}")
        else:
            logger.warning("[DREAMINA] 服务已初始化，但无可用账户")

    async def reload_accounts(self) -> None:
        accounts = await asyncio.to_thread(load_dreamina_accounts_sync)
        if accounts is None:
            accounts = []
        self._accounts = [
            acc for acc in accounts
            if acc.get("status") == "active" and acc.get("session_id")
        ]
        logger.info(f"[DREAMINA] 已加载 {len(self._accounts)} 个可用账户")

    async def _pick_account(self) -> Optional[Dict]:
        async with self._lock:
            if not self._accounts:
                return None
            account = self._accounts[self._index % len(self._accounts)]
            self._index += 1
            return account

    @property
    def available_count(self) -> int:
        return len(self._accounts)

    # ==================== 底层 API 请求 ====================

    async def _request(
        self,
        method: str,
        uri: str,
        session_id: str,
        data: Optional[Dict] = None,
        extra_params: Optional[Dict] = None,
    ) -> Any:
        """发送 Dreamina API 请求"""
        sign_value, device_time = _sign(uri)
        url = f"{API_BASE_URL}{uri}"

        params = {
            "aid": DEFAULT_ASSISTANT_ID,
            "device_platform": "web",
            "region": "US",
            "da_version": DA_VERSION,
            "os": "windows",
            "web_component_open_flag": "0",
            "web_version": WEB_VERSION,
            "aigc_features": "app_lip_sync",
            **(extra_params or {}),
        }

        headers = {
            **FAKE_HEADERS,
            "Cookie": _generate_cookie(session_id),
            "Device-Time": str(device_time),
            "Did": self._device_id,
            "Sign": sign_value,
            "Sign-Ver": "1",
            "Tdid": "",
        }

        resp = await self._http.request(
            method, url, params=params, headers=headers, json=data
        )

        if resp.status_code != 200:
            raise HTTPException(502, f"Dreamina API HTTP {resp.status_code}")

        body = resp.json()
        ret = body.get("ret")
        if ret == "0" or ret == 0:
            return body.get("data")

        errmsg = body.get("errmsg", "未知错误")
        logger.error(f"[DREAMINA] API 错误: ret={ret}, errmsg={errmsg}")
        raise HTTPException(502, f"Dreamina API 错误: {errmsg}")

    async def _request_commerce(
        self,
        method: str,
        uri: str,
        session_id: str,
        data: Optional[Dict] = None,
    ) -> Any:
        """发送积分相关 API 请求 (commerce.us.capcut.com)"""
        sign_value, device_time = _sign(uri)
        url = f"{COMMERCE_API_URL}{uri}"

        params = {
            "aid": DEFAULT_ASSISTANT_ID,
            "device_platform": "web",
            "region": "US",
            "da_version": DA_VERSION,
            "os": "windows",
            "web_component_open_flag": "0",
            "web_version": WEB_VERSION,
            "aigc_features": "app_lip_sync",
        }

        headers = {
            **FAKE_HEADERS,
            "Cookie": _generate_cookie(session_id),
            "Device-Time": str(device_time),
            "Did": self._device_id,
            "Sign": sign_value,
            "Sign-Ver": "1",
            "Tdid": "",
        }

        resp = await self._http.request(
            method, url, params=params, headers=headers, json=data
        )

        if resp.status_code != 200:
            raise Exception(f"Commerce API HTTP {resp.status_code}")

        body = resp.json()
        ret = body.get("ret")
        if ret == "0" or ret == 0:
            return body.get("data")

        errmsg = body.get("errmsg", "未知错误")
        raise Exception(f"Commerce API 错误: {errmsg}")

    # ==================== 积分管理 ====================

    async def _get_credit(self, session_id: str) -> int:
        """查询账户积分"""
        try:
            result = await self._request_commerce(
                "POST", "/commerce/v1/benefits/user_credit_history",
                session_id, data={"count": 20, "cursor": "0"}
            )
            total = (result or {}).get("total_credit", 0)
            return total
        except Exception as e:
            logger.warning(f"[DREAMINA] 查询积分失败: {e}")
            return -1  # -1 表示查询失败，不阻断流程

    async def _receive_credit(self, session_id: str) -> int:
        """领取每日积分"""
        try:
            result = await self._request_commerce(
                "POST", "/commerce/v1/benefits/credit_receive",
                session_id, data={"time_zone": "America/New_York"}
            )
            total = (result or {}).get("cur_total_credits", 0)
            receive = (result or {}).get("receive_quota", 0)
            logger.info(f"[DREAMINA] 积分领取成功: +{receive}, 总积分: {total}")
            return total
        except Exception as e:
            logger.warning(f"[DREAMINA] 领取积分失败: {e}")
            return 0

    async def _ensure_credit(self, session_id: str, account_email: str) -> None:
        """确保账户有积分，不足时尝试领取"""
        credit = await self._get_credit(session_id)
        logger.info(f"[DREAMINA] 账户 {account_email} 积分: {credit}")
        if credit == 0:
            logger.info(f"[DREAMINA] 账户 {account_email} 积分为0，尝试领取...")
            await self._receive_credit(session_id)

    # ==================== 图片生成 ====================

    async def generate_image(
        self,
        prompt: str,
        model: str = "dreamina-4.5",
        size: str = "2048x2048",
        sample_strength: float = 0.5,
        request_id: str = "",
    ) -> Dict:
        """生成图片（主入口），积分不足时自动切换下一个账户"""
        # 最多尝试所有可用账户
        max_tries = max(len(self._accounts), 1)
        last_error = None

        for attempt in range(max_tries):
            # 1. 选取账户
            account = await self._pick_account()
            if not account:
                await self.reload_accounts()
                account = await self._pick_account()
                if not account:
                    raise HTTPException(503, "无可用 Dreamina 账户")

            session_id = account["session_id"]
            account_email = account.get("email", "unknown")
            logger.info(
                f"[DREAMINA] [req_{request_id}] 账户: {account_email} "
                f"(尝试 {attempt + 1}/{max_tries}), "
                f"模型: {model}, prompt: {prompt[:80]}"
            )

            try:
                # 2. 检查并领取积分
                await self._ensure_credit(session_id, account_email)

                # 3. 创建生成任务
                history_id = await self._create_task(
                    session_id, prompt, model, size, sample_strength, request_id
                )
                logger.info(f"[DREAMINA] [req_{request_id}] 任务已创建: {history_id}")

                # 3. 轮询结果
                images = await self._poll_result(session_id, history_id, request_id)
                logger.info(
                    f"[DREAMINA] [req_{request_id}] 生成完成: {len(images)} 张图片"
                )
                return {"images": images, "account_id": account["id"]}

            except HTTPException as e:
                last_error = e
                detail_lower = str(e.detail).lower()
                # 可恢复错误：积分不足 / 登录失效 / 账户问题 → 切换下一个账户
                if any(kw in detail_lower for kw in ("credit", "benefit", "login", "session", "auth", "token")):
                    logger.warning(
                        f"[DREAMINA] [req_{request_id}] 账户 {account_email} 不可用 ({e.detail})，切换下一个账户"
                    )
                    continue
                raise
            except Exception as e:
                logger.error(
                    f"[DREAMINA] [req_{request_id}] 生成失败: {type(e).__name__}: {e}"
                )
                raise HTTPException(502, f"Dreamina 生成失败: {e}")

        # 所有账户都不可用
        logger.error(f"[DREAMINA] [req_{request_id}] 所有 {max_tries} 个账户均不可用")
        raise last_error or HTTPException(503, "所有 Dreamina 账户不可用")

    async def _create_task(
        self,
        session_id: str,
        prompt: str,
        model: str,
        size: str,
        sample_strength: float,
        request_id: str,
    ) -> str:
        """调用 /mweb/v1/aigc_draft/generate 创建图片生成任务"""
        internal_model = IMAGE_MODEL_MAP.get(model, DEFAULT_IMAGE_MODEL)
        is_external = internal_model.startswith("external_model_")
        width, height = _parse_size(size)

        # 外部模型不支持 2K 分辨率，强制限制到 1K
        if is_external and (width > 1024 or height > 1024):
            scale = 1024 / max(width, height)
            width = int(width * scale)
            height = int(height * scale)

        resolution_type = "2k" if width >= 2048 or height >= 2048 else "1k"

        component_id = _uuid()
        submit_id = _uuid()

        # 构建 core_param — 外部模型跳过不兼容参数
        core_param = {
            "type": "",
            "id": _uuid(),
            "model": internal_model,
            "prompt": prompt,
            "negative_prompt": "",
            "seed": random.randint(100000000, 3500000000),
            "image_ratio": _get_image_ratio(width, height),
        }

        if not is_external:
            # 原生 Dreamina 模型支持的额外参数
            core_param["sample_strength"] = sample_strength
            core_param["large_image_info"] = {
                "type": "",
                "id": _uuid(),
                "height": height,
                "width": width,
                "resolution_type": resolution_type,
            }
            core_param["intelligent_ratio"] = False

        draft_content = {
            "type": "draft",
            "id": _uuid(),
            "min_version": "3.0.2",
            "min_features": [],
            "is_from_tsn": True,
            "version": DRAFT_VERSION,
            "main_component_id": component_id,
            "component_list": [
                {
                    "type": "image_base_component",
                    "id": component_id,
                    "min_version": "3.0.2",
                    "aigc_mode": "workbench",
                    "metadata": {
                        "type": "",
                        "id": _uuid(),
                        "created_platform": 3,
                        "created_platform_version": "",
                        "created_time_in_ms": str(int(time.time() * 1000)),
                        "created_did": "",
                    },
                    "generate_type": "generate",
                    "abilities": {
                        "type": "",
                        "id": _uuid(),
                        "generate": {
                            "type": "",
                            "id": _uuid(),
                            "core_param": core_param,
                        },
                        "gen_option": {
                            "type": "",
                            "id": _uuid(),
                            "generate_all": False,
                        },
                    },
                },
            ],
        }

        body = {
            "extend": {"root_model": internal_model},
            "submit_id": submit_id,
            "metrics_extra": json.dumps({
                "promptSource": "custom",
                "generateCount": 1,
                "enterFrom": "click",
                "generateId": submit_id,
                "isRegenerate": False,
            }),
            "draft_content": json.dumps(draft_content),
            "http_common_info": {"aid": int(DEFAULT_ASSISTANT_ID)},
        }

        result = await self._request(
            "POST", "/mweb/v1/aigc_draft/generate", session_id, data=body
        )

        history_id = (result or {}).get("aigc_data", {}).get("history_record_id")
        if not history_id:
            logger.error(f"[DREAMINA] [req_{request_id}] 响应中无 history_record_id: {result}")
            raise HTTPException(502, "Dreamina 返回无效响应")

        return history_id

    async def _poll_result(
        self,
        session_id: str,
        history_id: str,
        request_id: str,
    ) -> List[Dict]:
        """轮询 /mweb/v1/get_history_by_ids 获取生成结果"""
        for poll_count in range(1, POLL_MAX_COUNT + 1):
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

            try:
                result = await self._request(
                    "POST",
                    "/mweb/v1/get_history_by_ids",
                    session_id,
                    data={"history_ids": [history_id]},
                )
            except Exception as e:
                logger.warning(f"[DREAMINA] [req_{request_id}] 轮询异常: {e}")
                continue

            if not result or history_id not in result:
                logger.warning(
                    f"[DREAMINA] [req_{request_id}] 记录不存在: {history_id}"
                )
                continue

            record = result[history_id]
            status = record.get("status", 0)
            item_list = record.get("item_list") or []
            fail_code = record.get("fail_code")

            # 失败
            if status == STATUS_FAILED:
                if fail_code == "2038":
                    raise HTTPException(400, "Dreamina: 内容被过滤（违规）")
                raise HTTPException(
                    502, f"Dreamina 生成失败 (fail_code={fail_code})"
                )

            # 完成或有图片
            if status == STATUS_COMPLETED or item_list:
                images = self._extract_images(item_list)
                if images:
                    return images

            # 进度日志
            if poll_count % 30 == 0:
                logger.info(
                    f"[DREAMINA] [req_{request_id}] 轮询中... "
                    f"第 {poll_count} 次, status={status}, items={len(item_list)}"
                )

        raise HTTPException(504, "Dreamina 生成超时")

    @staticmethod
    def _extract_images(item_list: list) -> List[Dict]:
        """从 item_list 提取图片 URL"""
        images = []
        for item in item_list:
            url = None
            # 优先 large_images
            large_imgs = (item.get("image") or {}).get("large_images") or []
            if large_imgs and large_imgs[0].get("image_url"):
                url = large_imgs[0]["image_url"]
            # 备选 cover_url
            elif (item.get("common_attr") or {}).get("cover_url"):
                url = item["common_attr"]["cover_url"]

            if url:
                images.append({"url": url})
        return images

    # ==================== 清理 ====================

    async def close(self) -> None:
        await self._http.aclose()
