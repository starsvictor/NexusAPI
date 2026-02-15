"""
Dreamina 独立注册服务

参考 RegisterService 模式，简化版本。
不依赖 multi_account_mgr 等 Gemini 相关组件，
仅使用 BaseTaskService 的任务管理和日志功能。
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from core.base_task_service import BaseTask, BaseTaskService, TaskCancelledError, TaskStatus
from core.config import config
from core.mail_providers import create_temp_mail_client
from core.dreamina_automation import DreaminaAutomation
from core.proxy_utils import parse_proxy_setting

logger = logging.getLogger("dreamina.register")


@dataclass
class DreaminaRegisterTask(BaseTask):
    """Dreamina 注册任务数据类"""
    count: int = 0
    domain: Optional[str] = None
    mail_provider: Optional[str] = None

    def to_dict(self) -> dict:
        """转换为字典"""
        base_dict = super().to_dict()
        base_dict["count"] = self.count
        base_dict["domain"] = self.domain
        base_dict["mail_provider"] = self.mail_provider
        return base_dict


class DreaminaRegisterService(BaseTaskService[DreaminaRegisterTask]):
    """
    Dreamina 独立注册服务

    继承 BaseTaskService 获取任务管理、日志、取消等能力，
    但不使用 multi_account_mgr、http_client 等 Gemini 专用参数。
    """

    def __init__(self) -> None:
        # Dreamina 不需要 Gemini 的账户管理器等组件，传入 None
        super().__init__(
            multi_account_mgr=None,
            http_client=None,
            user_agent="",
            retry_policy=None,
            session_cache_ttl_seconds=0,
            global_stats_provider=lambda: {},
            set_multi_account_mgr=None,
            log_prefix="DREAMINA_REG",
        )

    def _get_running_task(self) -> Optional[DreaminaRegisterTask]:
        """获取正在运行或等待中的任务"""
        for task in self._tasks.values():
            if isinstance(task, DreaminaRegisterTask) and task.status in (
                TaskStatus.PENDING,
                TaskStatus.RUNNING,
            ):
                return task
        return None

    async def start_register(
        self,
        count: Optional[int] = None,
        domain: Optional[str] = None,
        mail_provider: Optional[str] = None,
    ) -> DreaminaRegisterTask:
        """
        启动 Dreamina 注册任务

        - 如果有正在运行的任务，将新数量追加到该任务
        - 如果没有正在运行的任务，创建新任务
        """
        async with self._lock:
            # 确定邮箱提供商
            mail_provider_value = (mail_provider or "").strip().lower()
            if not mail_provider_value:
                mail_provider_value = (config.basic.temp_mail_provider or "moemail").lower()

            # 确定域名（仅 DuckMail 使用 register_domain）
            domain_value = (domain or "").strip()
            if not domain_value:
                if mail_provider_value == "duckmail":
                    domain_value = (config.basic.register_domain or "").strip() or None
                else:
                    domain_value = None

            register_count = count or config.basic.dreamina_register_default_count
            register_count = max(1, int(register_count))

            # 检查是否有正在运行的任务
            running_task = self._get_running_task()
            if running_task:
                running_task.count += register_count
                self._append_log(
                    running_task,
                    "info",
                    f"追加 {register_count} 个账户到现有任务 (总计: {running_task.count})",
                )
                return running_task

            # 创建新任务
            task = DreaminaRegisterTask(
                id=str(uuid.uuid4()),
                count=register_count,
                domain=domain_value,
                mail_provider=mail_provider_value,
            )
            self._tasks[task.id] = task
            self._append_log(
                task,
                "info",
                f"创建 Dreamina 注册任务 (数量: {register_count}, "
                f"域名: {domain_value or 'default'}, 提供商: {mail_provider_value})",
            )

            # 直接启动任务
            self._current_task_id = task.id
            asyncio.create_task(self._run_task_directly(task))
            return task

    async def _run_task_directly(self, task: DreaminaRegisterTask) -> None:
        """直接执行任务"""
        try:
            await self._run_one_task(task)
        finally:
            async with self._lock:
                if self._current_task_id == task.id:
                    self._current_task_id = None

    def _execute_task(self, task: DreaminaRegisterTask):
        """实现 BaseTaskService 要求的抽象方法"""
        return self._run_register_loop(task)

    async def _run_register_loop(self, task: DreaminaRegisterTask) -> None:
        """异步循环注册（支持取消）"""
        loop = asyncio.get_running_loop()
        self._append_log(task, "info", f"Dreamina 注册任务已启动 (共 {task.count} 个账号)")

        for idx in range(task.count):
            # 检查取消
            if task.cancel_requested:
                self._append_log(
                    task,
                    "warning",
                    f"dreamina register task cancelled: {task.cancel_reason or 'cancelled'}",
                )
                task.status = TaskStatus.CANCELLED
                task.finished_at = time.time()
                return

            try:
                self._append_log(task, "info", f"进度: {idx + 1}/{task.count}")
                result = await loop.run_in_executor(
                    self._executor,
                    self._register_one,
                    task.domain,
                    task.mail_provider,
                    task,
                )
            except TaskCancelledError:
                task.status = TaskStatus.CANCELLED
                task.finished_at = time.time()
                return
            except Exception as exc:
                result = {"success": False, "error": str(exc)}

            task.progress += 1
            task.results.append(result)

            if result.get("success"):
                task.success_count += 1
                email = result.get("email", "未知")
                self._append_log(task, "info", f"注册成功: {email}")
            else:
                task.fail_count += 1
                error = result.get("error", "未知错误")
                self._append_log(task, "error", f"注册失败: {error}")

        # 任务结束
        if task.cancel_requested:
            task.status = TaskStatus.CANCELLED
        else:
            task.status = TaskStatus.SUCCESS if task.fail_count == 0 else TaskStatus.FAILED
        task.finished_at = time.time()
        self._current_task_id = None
        self._append_log(
            task,
            "info",
            f"Dreamina 注册任务完成 "
            f"(成功: {task.success_count}, 失败: {task.fail_count}, 总计: {task.count})",
        )

    def _register_one(
        self,
        domain: Optional[str],
        mail_provider: Optional[str],
        task: DreaminaRegisterTask,
    ) -> dict:
        """单次 Dreamina 注册流程（在线程池中执行）"""
        log_cb = lambda level, message: self._append_log(task, level, message)

        log_cb("info", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        log_cb("info", "开始注册新 Dreamina 账户")
        log_cb("info", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        # ---- 步骤 1: 创建临时邮箱 ----
        temp_mail_provider = (mail_provider or "").strip().lower()
        if not temp_mail_provider:
            temp_mail_provider = (config.basic.temp_mail_provider or "moemail").lower()

        log_cb("info", f"步骤 1/3: 注册临时邮箱 (提供商={temp_mail_provider})...")

        # 检查 freemail 是否配置了 JWT Token
        if temp_mail_provider == "freemail" and not config.basic.freemail_jwt_token:
            log_cb("error", "Freemail JWT Token 未配置")
            return {"success": False, "error": "Freemail JWT Token 未配置"}

        client = create_temp_mail_client(
            temp_mail_provider,
            domain=domain,
            log_cb=log_cb,
        )

        if not client.register_account(domain=domain):
            log_cb("error", f"{temp_mail_provider} 邮箱注册失败")
            return {"success": False, "error": f"{temp_mail_provider} 注册失败"}

        log_cb("info", f"邮箱注册成功: {client.email}")

        # ---- 步骤 2: 启动浏览器 ----
        headless = config.basic.browser_headless
        proxy_for_auth, _ = parse_proxy_setting(config.basic.proxy_for_auth)

        log_cb("info", f"步骤 2/3: 启动浏览器 (无头模式={headless})...")

        automation = DreaminaAutomation(
            proxy=proxy_for_auth,
            headless=headless,
            log_callback=log_cb,
        )
        # 注册取消回调：取消时关闭浏览器
        self._add_cancel_hook(task.id, lambda: getattr(automation, "stop", lambda: None)())

        # ---- 步骤 3: 执行 Dreamina 注册 ----
        try:
            log_cb("info", "步骤 3/3: 执行 Dreamina 自动注册...")
            result = automation.register_and_extract(client.email, client)
        except Exception as exc:
            log_cb("error", f"自动注册异常: {exc}")
            return {"success": False, "error": str(exc)}

        if not result.get("success"):
            error = result.get("error", "自动化流程失败")
            log_cb("error", f"自动注册失败: {error}")
            return {"success": False, "error": error}

        # ---- 注册成功，保存到数据库 ----
        email = result.get("email", client.email)
        password = result.get("password", "")
        session_id = result.get("session_id", "")

        log_cb("info", "注册成功，正在保存账户信息...")

        try:
            from core.storage import save_dreamina_account_sync

            account_data = {
                "id": str(uuid.uuid4()),
                "email": email,
                "password": password,
                "session_id": session_id,
                "status": "active",
            }
            save_dreamina_account_sync(account_data)
            log_cb("info", "账户信息已保存到数据库")
        except Exception as exc:
            logger.warning("[DREAMINA_REG] 保存账户到数据库失败: %s", exc)

        log_cb("info", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        log_cb("info", f"Dreamina 账户注册完成: {email}")
        log_cb("info", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        return {
            "success": True,
            "email": email,
            "password": password,
            "session_id": session_id,
        }
