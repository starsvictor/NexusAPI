"""
Dreamina 自动化注册模块

使用 DrissionPage 在 dreamina.capcut.com 上自动注册账号，
作为 Gemini Business 注册流程的可选后置步骤。
"""
import os
import random
import secrets
import string
import time
from datetime import datetime
from typing import Optional

from DrissionPage import ChromiumPage, ChromiumOptions
from core.base_task_service import TaskCancelledError


# 常量
DREAMINA_URL = "https://dreamina.capcut.com/ai-tool/home"

# Linux 下常见的 Chromium 路径
CHROMIUM_PATHS = [
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
]


def _find_chromium_path() -> Optional[str]:
    """查找可用的 Chromium/Chrome 浏览器路径"""
    for path in CHROMIUM_PATHS:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def _generate_password() -> str:
    """生成随机密码（保证包含大写、小写、数字和特殊字符）"""
    special = "!@#$%"
    chars = string.ascii_letters + string.digits + special
    while True:
        password = "".join(secrets.choice(chars) for _ in range(14))
        if (any(c in string.ascii_lowercase for c in password)
                and any(c in string.ascii_uppercase for c in password)
                and any(c in string.digits for c in password)
                and any(c in special for c in password)):
            return password


class DreaminaAutomation:
    """Dreamina 自动化注册"""

    def __init__(
        self,
        user_agent: str = "",
        proxy: str = "",
        headless: bool = True,
        timeout: int = 60,
        log_callback=None,
    ) -> None:
        self.user_agent = user_agent or self._get_ua()
        self.proxy = proxy
        self.headless = headless
        self.timeout = timeout
        self.log_callback = log_callback
        self._page = None

    def stop(self) -> None:
        """外部请求停止：关闭浏览器实例"""
        page = self._page
        if page:
            try:
                page.quit()
            except Exception:
                pass

    def register_and_extract(self, email: str, mail_client) -> dict:
        """执行 Dreamina 注册并提取 session

        Args:
            email: 邮箱地址（复用 Gemini 注册的同一邮箱）
            mail_client: 邮箱客户端（用于获取验证码）

        Returns:
            dict: {success, email, password, session_id} 或 {success: False, error}
        """
        page = None
        user_data_dir = None
        try:
            page = self._create_page()
            user_data_dir = getattr(page, "user_data_dir", None)
            self._page = page
            return self._run_flow(page, email, mail_client)
        except TaskCancelledError:
            raise
        except Exception as exc:
            self._log("error", f"[Dreamina] 自动化异常: {exc}")
            return {"success": False, "error": str(exc)}
        finally:
            if page:
                try:
                    page.quit()
                except Exception:
                    pass
            self._page = None
            self._cleanup_user_data(user_data_dir)

    def _create_page(self) -> ChromiumPage:
        """创建浏览器页面（与 GeminiAutomation 一致）"""
        options = ChromiumOptions()

        chromium_path = _find_chromium_path()
        if chromium_path:
            options.set_browser_path(chromium_path)

        options.set_argument("--incognito")
        options.set_argument("--no-sandbox")
        options.set_argument("--disable-dev-shm-usage")
        options.set_argument("--disable-setuid-sandbox")
        options.set_argument("--disable-blink-features=AutomationControlled")
        options.set_argument("--window-size=1280,800")
        options.set_user_agent(self.user_agent)
        options.set_argument("--lang=en-US")
        options.set_pref("intl.accept_languages", "en-US,en")

        if self.proxy:
            options.set_argument(f"--proxy-server={self.proxy}")

        if self.headless:
            options.set_argument("--headless=new")
            options.set_argument("--disable-gpu")
            options.set_argument("--no-first-run")
            options.set_argument("--disable-extensions")
            options.set_argument("--disable-infobars")
            options.set_argument("--enable-features=NetworkService,NetworkServiceInProcess")

        options.auto_port()
        page = ChromiumPage(options)
        page.set.timeouts(self.timeout)

        # 反检测
        if self.headless:
            try:
                page.run_cdp("Page.addScriptToEvaluateOnNewDocument", source="""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                    Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                    window.chrome = {runtime: {}};
                    Object.defineProperty(navigator, 'maxTouchPoints', {get: () => 1});
                    Object.defineProperty(navigator, 'platform', {get: () => 'Win32'});
                    Object.defineProperty(navigator, 'vendor', {get: () => 'Google Inc.'});
                    Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => 8});
                    Object.defineProperty(navigator, 'deviceMemory', {get: () => 8});
                """)
            except Exception:
                pass

        return page

    def _run_flow(self, page, email: str, mail_client) -> dict:
        """执行注册流程"""
        password = _generate_password()

        # Step 1: 打开 Dreamina 主页
        self._log("info", "[Dreamina] 打开主页...")
        page.get(DREAMINA_URL, timeout=self.timeout)
        time.sleep(3)

        # Step 2: 点击 Sign in / Sign up 入口
        self._log("info", "[Dreamina] 寻找登录/注册入口...")
        if not self._click_sign_in_entry(page):
            self._save_screenshot(page, "dreamina_entry_not_found")
            return {"success": False, "error": "登录/注册入口未找到"}

        # Step 3: 选择 Email 方式
        time.sleep(2)
        self._click_continue_with_email(page)

        # Step 4: 切换到 Sign up 模式（如果当前是登录页面）
        time.sleep(2)
        self._switch_to_signup(page)

        # Step 5: 填写邮箱和密码
        self._log("info", f"[Dreamina] 填写邮箱: {email}")
        if not self._fill_credentials(page, email, password):
            self._save_screenshot(page, "dreamina_fill_credentials_failed")
            return {"success": False, "error": "填写邮箱/密码失败"}

        # Step 6: 点击 Continue / Sign up（记录时间戳用于过滤旧验证码）
        self._log("info", "[Dreamina] 点击 Continue...")
        code_request_time = datetime.now()
        self._click_continue_button(page)

        # Step 7: 等待并填入验证码
        time.sleep(3)
        self._log("info", "[Dreamina] 等待验证码...")
        code = mail_client.poll_for_code(timeout=60, interval=5, since_time=code_request_time)
        if not code:
            self._save_screenshot(page, "dreamina_code_timeout")
            return {"success": False, "error": "验证码获取超时"}

        self._log("info", f"[Dreamina] 收到验证码: {code}")
        self._fill_verification_code(page, code)

        # 填完后尝试点击确认按钮
        time.sleep(2)
        self._click_confirm_button(page)

        # Step 8: 处理生日页面（如果出现）
        time.sleep(4)
        self._handle_birthday_page(page)

        # Step 9: 等待 sessionid cookie
        self._log("info", "[Dreamina] 等待 Session...")
        session_id = self._wait_for_session(page)
        if not session_id:
            self._save_screenshot(page, "dreamina_session_not_found")
            return {"success": False, "error": "未获取到 sessionid"}

        self._log("info", f"[Dreamina] 注册成功! Session: {session_id[:10]}...")
        return {
            "success": True,
            "email": email,
            "password": password,
            "session_id": session_id,
        }

    # ==================== 页面交互方法 ====================

    def _click_sign_in_entry(self, page) -> bool:
        """点击 Sign in / Sign up 入口"""
        try:
            # 查找包含 Sign in 或 Sign up 文本的元素
            btn = page.ele("xpath://*[contains(text(), 'Sign in') or contains(text(), 'Sign up')]", timeout=10)
            if btn:
                page.run_js("arguments[0].click();", btn)
                time.sleep(2)
                return True
        except Exception as e:
            self._log("warning", f"[Dreamina] 点击入口失败: {e}")
        return False

    def _click_continue_with_email(self, page) -> None:
        """点击 Continue with email"""
        try:
            btn = page.ele("xpath://*[contains(text(), 'Continue with email')]", timeout=5)
            if btn:
                page.run_js("arguments[0].click();", btn)
        except Exception:
            pass

    def _switch_to_signup(self, page) -> None:
        """切换到注册模式"""
        try:
            page_text = page.html
            if "Welcome back" in page_text or "Log in" in page_text:
                self._log("info", "[Dreamina] 切换至注册模式...")
                btn = page.ele("xpath://span[contains(text(), 'Sign up')] | //a[contains(text(), 'Sign up')]", timeout=3)
                if btn:
                    page.run_js("arguments[0].click();", btn)
                    time.sleep(2)
        except Exception:
            pass

    def _fill_credentials(self, page, email: str, password: str) -> bool:
        """填写邮箱和密码"""
        try:
            email_input = page.ele("xpath://input[contains(@placeholder, 'email') or @type='email']", timeout=10)
            if not email_input:
                return False

            email_input.clear()
            self._simulate_human_input(email_input, email)

            pass_inputs = page.eles("xpath://input[@type='password']")
            if pass_inputs:
                self._simulate_human_input(pass_inputs[0], password)

            return True
        except Exception as e:
            self._log("error", f"[Dreamina] 填写凭证失败: {e}")
            return False

    def _click_continue_button(self, page) -> None:
        """点击 Continue 或 Sign up 按钮"""
        try:
            btn = page.ele("xpath://button[contains(text(), 'Continue') or contains(text(), 'Sign up')]", timeout=5)
            if btn:
                btn.click()
                return
        except Exception:
            pass
        # 降级：回车提交
        try:
            page.actions.key_down("ENTER").key_up("ENTER")
        except Exception:
            pass

    def _fill_verification_code(self, page, code: str) -> None:
        """填入验证码（支持分割输入框）"""
        # 策略 A: 查找多个分割输入框
        try:
            inputs = page.eles("tag:input")
            visible_inputs = [inp for inp in inputs if inp.states.is_displayed and inp.attr("type") != "hidden"]

            # 过滤掉搜索框等
            code_inputs = []
            for inp in visible_inputs:
                placeholder = (inp.attr("placeholder") or "").lower()
                if "search" not in placeholder and "email" not in placeholder:
                    code_inputs.append(inp)

            if 4 <= len(code_inputs) <= 6:
                self._log("info", f"[Dreamina] 识别到 {len(code_inputs)} 个分割输入框")
                for i, char in enumerate(code):
                    if i < len(code_inputs):
                        code_inputs[i].input(char)
                        time.sleep(0.1)
                return
        except Exception:
            pass

        # 策略 B: 聚焦第一个输入框，逐字符键入
        self._log("info", "[Dreamina] 使用键盘模拟输入验证码...")
        try:
            first_input = page.ele("tag:input", timeout=3)
            if first_input:
                first_input.click()
                time.sleep(0.3)
                for char in code:
                    page.actions.type(char)
                    time.sleep(0.1)
        except Exception as e:
            self._log("warning", f"[Dreamina] 验证码输入失败: {e}")

    def _click_confirm_button(self, page) -> None:
        """点击 Next / Sign up / Confirm 按钮"""
        keywords = ["Next", "Sign up", "Confirm"]
        try:
            buttons = page.eles("tag:button")
            for btn in buttons:
                text = (btn.text or "").strip()
                if text and any(kw in text for kw in keywords) and btn.states.is_displayed:
                    btn.click()
                    return
        except Exception:
            pass

    def _handle_birthday_page(self, page) -> None:
        """处理生日页面"""
        try:
            page_text = (page.html or "").lower()
            if "birthday" not in page_text:
                return

            self._log("info", "[Dreamina] 填写生日...")

            # 年份输入
            year_input = page.ele("xpath://input[contains(@placeholder, 'YYYY') or contains(@placeholder, 'Year')]", timeout=3)
            if not year_input:
                inputs = page.eles("tag:input")
                visible = [i for i in inputs if i.states.is_displayed]
                year_input = visible[0] if visible else None

            if year_input:
                year_input.click()
                time.sleep(0.2)
                year_input.clear()
                rand_year = str(random.randint(1995, 2005))
                year_input.input(rand_year)
                time.sleep(0.5)

            # 月份选择
            try:
                month_trigger = page.ele("xpath://*[text()='Month']", timeout=2)
                if month_trigger:
                    page.run_js("arguments[0].click();", month_trigger)
                    time.sleep(1)
                    months = ["January", "February", "March", "April", "May", "June",
                              "July", "August", "September", "October", "November", "December"]
                    rand_month = random.choice(months)
                    month_opt = page.ele(f"xpath://*[contains(text(), '{rand_month}')]", timeout=2)
                    if month_opt:
                        page.run_js("arguments[0].click();", month_opt)
            except Exception:
                # 键盘流兜底
                page.actions.key_down("TAB").key_up("TAB")
                time.sleep(0.2)
                page.actions.key_down("ENTER").key_up("ENTER")
                time.sleep(0.2)
                page.actions.key_down("DOWN").key_up("DOWN")
                page.actions.key_down("ENTER").key_up("ENTER")

            time.sleep(1)

            # 日期选择
            try:
                day_trigger = page.ele("xpath://*[text()='Day']", timeout=2)
                if day_trigger:
                    page.run_js("arguments[0].click();", day_trigger)
                    time.sleep(1)
                    rand_day = str(random.randint(1, 28))
                    day_opt = page.ele(f"xpath://div[text()='{rand_day}'] | //li[text()='{rand_day}'] | //span[text()='{rand_day}']", timeout=2)
                    if day_opt:
                        page.run_js("arguments[0].click();", day_opt)
            except Exception:
                page.actions.key_down("TAB").key_up("TAB")
                time.sleep(0.2)
                page.actions.key_down("ENTER").key_up("ENTER")
                time.sleep(0.2)
                page.actions.key_down("DOWN").key_up("DOWN")
                page.actions.key_down("DOWN").key_up("DOWN")
                page.actions.key_down("ENTER").key_up("ENTER")

            # 点击 Next
            time.sleep(1)
            next_keywords = ["Next", "Submit", "Confirm"]
            try:
                buttons = page.eles("tag:button")
                for btn in buttons:
                    text = (btn.text or "").strip()
                    if text and any(kw in text for kw in next_keywords) and btn.states.is_displayed:
                        page.run_js("arguments[0].click();", btn)
                        break
                else:
                    page.actions.key_down("ENTER").key_up("ENTER")
            except Exception:
                page.actions.key_down("ENTER").key_up("ENTER")

        except Exception as e:
            self._log("warning", f"[Dreamina] 生日填写异常: {e}")

    def _wait_for_session(self, page, timeout: int = 30) -> Optional[str]:
        """等待 sessionid cookie 出现"""
        for _ in range(timeout // 2):
            try:
                cookies = page.cookies()
                for cookie in cookies:
                    if cookie.get("name") == "sessionid" and cookie.get("value"):
                        return cookie["value"]
            except Exception:
                pass
            time.sleep(2)
        return None

    # ==================== 工具方法 ====================

    def _simulate_human_input(self, element, text: str) -> bool:
        """模拟人类输入（点击聚焦后逐字符键入）"""
        try:
            element.click()
            time.sleep(random.uniform(0.1, 0.3))
            # 使用 actions.type() 逐字符键入，避免 element.input() 每次清空的问题
            page = element.owner
            for char in text:
                page.actions.type(char)
                time.sleep(random.uniform(0.03, 0.1))
            time.sleep(random.uniform(0.2, 0.5))
            return True
        except Exception:
            # 降级：直接使用 input 一次性输入
            try:
                element.input(text, clear=True)
                return True
            except Exception:
                return False

    def _save_screenshot(self, page, name: str) -> None:
        """保存截图"""
        try:
            from core.storage import _data_file_path
            screenshot_dir = _data_file_path("automation")
            os.makedirs(screenshot_dir, exist_ok=True)
            path = os.path.join(screenshot_dir, f"{name}_{int(time.time())}.png")
            page.get_screenshot(path=path)
        except Exception:
            pass

    def _log(self, level: str, message: str) -> None:
        """记录日志"""
        if self.log_callback:
            try:
                self.log_callback(level, message)
            except TaskCancelledError:
                raise
            except Exception:
                pass

    def _cleanup_user_data(self, user_data_dir: Optional[str]) -> None:
        """清理浏览器用户数据目录"""
        if not user_data_dir:
            return
        try:
            import shutil
            if os.path.exists(user_data_dir):
                shutil.rmtree(user_data_dir, ignore_errors=True)
        except Exception:
            pass

    @staticmethod
    def _get_ua() -> str:
        """生成随机 User-Agent"""
        v = random.choice(["120.0.0.0", "121.0.0.0", "122.0.0.0"])
        return f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{v} Safari/537.36"
