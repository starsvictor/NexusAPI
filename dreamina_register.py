import sys
import time
import random
import string
import re

print("[-] 系统正在启动 v2.5 (Simulated Typing)...")

try:
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.common.action_chains import ActionChains
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    print("[X] 缺少库。请运行: pip install selenium undetected-chromedriver requests")
    sys.exit(1)

# ================= 配置区 =================
TOTAL_ACCOUNTS = 10
MAIL_API = "https://mail.chatgpt.org.uk"
MAIL_KEY = "gpt-test"  
OUTPUT_FILE = "dreamina_accounts.txt"
DREAMINA_URL = "https://dreamina.capcut.com/ai-tool/home"

# ================= 工具函数 =================

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")

def create_http_session():
    s = requests.Session()
    s.mount("https://", HTTPAdapter(max_retries=Retry(total=3, backoff_factor=1)))
    return s

http = create_http_session()

def generate_password():
    chars = string.ascii_letters + string.digits + "!@#$%"
    return ''.join(random.choice(chars) for _ in range(14))

def create_temp_email():
    try:
        log("正在申请邮箱...")
        r = http.get(f"{MAIL_API}/api/generate-email", headers={"X-API-Key": MAIL_KEY}, timeout=20)
        if r.json().get('success'): return r.json()['data']['email']
    except Exception as e: log(f"邮箱异常: {e}")
    return None

def wait_for_code(email):
    log(f"等待 {email} 的验证码 (60s)...")
    start = time.time()
    seen = set()
    # 匹配模式： "code: XXXXXX" 或 "code is XXXXXX" (支持字母+数字混合)
    regex_pattern = r'verification code[:\s]+([A-Z0-9]{6})'
    
    while time.time() - start < 60:
        try:
            r = http.get(f"{MAIL_API}/api/emails", params={"email": email}, headers={"X-API-Key": MAIL_KEY})
            data = r.json().get('data', {}).get('emails', [])
            if data:
                content = data[0].get('content') or data[0].get('html_content') or ''
                text_content = re.sub('<[^<]+?>', ' ', content) # 清洗HTML
                
                if text_content and text_content not in seen:
                    seen.add(text_content)
                    match = re.search(regex_pattern, text_content, re.IGNORECASE)
                    if match:
                        code = match.group(1)
                        log(f"捕获混合验证码: {code}")
                        return code
        except: pass
        time.sleep(5)
    return None

# ================= 验证码填充逻辑 (v2.5 新增) =================

def fill_split_code(driver, code):
    """专门处理 6 位分割输入框"""
    actions = ActionChains(driver)
    
    # 策略 A: 尝试找到所有输入框并一一填入
    try:
        inputs = driver.find_elements(By.XPATH, "//input")
        # 过滤出可能是验证码框的 input (通常都很短)
        code_inputs = [inp for inp in inputs if inp.is_displayed() and inp.get_attribute("type") != "hidden"]
        
        # 如果恰好找到6个可见的框（大概率是验证码框）
        # 或者页面上只有极少的输入框（去掉了搜索栏之类的）
        target_inputs = []
        for inp in code_inputs:
            # 排除掉搜索框、邮箱框等，只留那种很短的框
            if "search" not in (inp.get_attribute("placeholder") or "").lower():
                target_inputs.append(inp)
                
        # 如果数量接近6个，尝试一一填入
        if 4 <= len(target_inputs) <= 6:
            log(f"识别到 {len(target_inputs)} 个分割输入框，尝试精准填充...")
            for i, char in enumerate(code):
                if i < len(target_inputs):
                    target_inputs[i].send_keys(char)
            return True
    except: pass

    # 策略 B (通用): 聚焦第一个框，然后也就是 "盲打"
    log("使用键盘模拟输入 (ActionChains)...")
    try:
        # 你的截图显示焦点已经在第一个格子里了，所以直接通过键盘敲击
        # 为了保险，先点一下页面中心空白处，或者尝试点第一个 input
        try:
            first_input = driver.find_element(By.TAG_NAME, "input")
            driver.execute_script("arguments[0].focus();", first_input)
            first_input.click()
        except: 
            # 如果找不到特定的，就点击 body 确保窗口激活
            driver.find_element(By.TAG_NAME, "body").click()
        
        time.sleep(0.5)
        # 逐个敲击按键
        for char in code:
            actions.send_keys(char).perform()
            time.sleep(0.1) # 稍微慢一点，让网页反应过来自动跳格
        return True
    except Exception as e:
        log(f"模拟输入失败: {e}")
        return False

# ================= 核心流程 =================

def register_one(driver):
    email = create_temp_email()
    if not email: return False
    password = generate_password()
    wait = WebDriverWait(driver, 20)
    
    try:
        log("加载主页...")
        driver.get(DREAMINA_URL)
        time.sleep(3)

        # 1. 登录/注册入口
        log("尝试寻找并点击登录/注册入口...")
        try:
            # 增加显式等待，并同时查找 Sign in 和 Sign up
            xpath = "//*[contains(text(), 'Sign in') or contains(text(), 'Sign up')]"
            btns = wait.until(EC.presence_of_all_elements_located((By.XPATH, xpath)))
            
            clicked = False
            for b in btns:
                if b.is_displayed():
                    # log(f"发现可见按钮: '{b.text}'，尝试点击...")
                    driver.execute_script("arguments[0].click();", b)
                    clicked = True
                    break
            
            if not clicked:
                log("未找到可见的 Sign in/Sign up 按钮")
        except Exception as e:
            log(f"点击入口操作跳过或失败: {e}")

        # 2. 选择 Email 方式
        time.sleep(2)
        try:
            email_btn = wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Continue with email')]")))
            driver.execute_script("arguments[0].click();", email_btn)
        except: pass

        # 3. 智能切换 Sign up
        time.sleep(2)
        if "Welcome back" in driver.page_source:
            # log("切换至注册模式 (Sign up)...")
            try:
                switch_btn = driver.find_element(By.XPATH, "//span[contains(text(), 'Sign up')] | //a[contains(text(), 'Sign up')]")
                driver.execute_script("arguments[0].click();", switch_btn)
                time.sleep(2)
            except: pass

        # 4. 填写邮箱 & 密码
        log(f"填写邮箱: {email}")
        try:
            email_inp = wait.until(EC.presence_of_element_located((By.XPATH, "//input[contains(@placeholder, 'email') or @type='email']")))
            email_inp.clear()
            email_inp.send_keys(email)
            
            pass_inp = driver.find_elements(By.XPATH, "//input[@type='password']")
            if pass_inp:
                pass_inp[0].send_keys(password)
        except: return False

        # 5. 点击 Continue
        log("点击 Continue...")
        try:
            time.sleep(1)
            cont_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Continue') or contains(text(), 'Sign up')]")))
            cont_btn.click()
        except: 
            # 暴力点击 Enter 键
            ActionChains(driver).send_keys(Keys.ENTER).perform()

        # 6. 等待并填入验证码
        time.sleep(3)
        code = wait_for_code(email)
        if code:
            log(f"开始填入验证码: {code}")
            fill_split_code(driver, code)
            
            # 填完后，通常会自动跳转，或者是通过 Next 按钮
            time.sleep(2)
            try:
                next_btn = driver.find_element(By.XPATH, "//button[contains(text(), 'Next') or contains(text(), 'Sign up') or contains(text(), 'Confirm')]")
                if next_btn.is_displayed():
                    next_btn.click()
            except: pass

        # 7. 生日处理
        time.sleep(4)
        page_content = driver.page_source.lower()
        if "birthday" in page_content or len(driver.find_elements(By.TAG_NAME, "select")) >= 1:
            log("填写生日...")
            try:
                actions = ActionChains(driver)
                
                # --- 1. 年份 (Year) ---
                # 寻找 placeholder 为 YYYY 或者 4位数的输入框，或者直接找第一个 input
                try:
                    # 尝试通过 placeholder 定位
                    year_input = driver.find_element(By.XPATH, "//input[contains(@placeholder, 'YYYY') or contains(@placeholder, 'Year')]")
                except:
                    # 兜底：找页面上第一个可见的 input
                    inputs = driver.find_elements(By.TAG_NAME, "input")
                    year_input = next((i for i in inputs if i.is_displayed()), None)
                
                if year_input:
                    # log("填写年份...")
                    driver.execute_script("arguments[0].click();", year_input)
                    time.sleep(0.3)
                    year_input.send_keys(Keys.CONTROL, "a")
                    year_input.send_keys(Keys.BACK_SPACE)
                    # 随机年份 1995-2005
                    rand_year = str(random.randint(1995, 2005))
                    year_input.send_keys(rand_year)
                    time.sleep(0.5)
                
                # --- 2. 月份 (Month) ---
                # log("选择月份...")
                try:
                    # 尝试点击显示 "Month" 的区域
                    month_trigger = driver.find_element(By.XPATH, "//*[text()='Month']")
                    driver.execute_script("arguments[0].click();", month_trigger)
                    time.sleep(1)
                    
                    # 随机月份
                    months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
                    rand_month = random.choice(months)
                    # log(f"随机选择月份: {rand_month}")
                    
                    # 使用 contains text 以防有空格
                    month_opt = driver.find_element(By.XPATH, f"//*[contains(text(), '{rand_month}')]")
                    driver.execute_script("arguments[0].click();", month_opt)
                except Exception as e:
                    # log(f"点击 Month 失败，尝试键盘流: {e}")
                    # 备用：Tab 过去，回车展开，下移选中
                    actions.send_keys(Keys.TAB).perform()
                    time.sleep(0.2)
                    actions.send_keys(Keys.ENTER).perform()
                    time.sleep(0.2)
                    actions.send_keys(Keys.DOWN).perform()
                    actions.send_keys(Keys.ENTER).perform()
                
                time.sleep(1)

                # --- 3. 日期 (Day) ---
                # log("选择日期...")
                try:
                    # 尝试点击显示 "Day" 的区域
                    day_trigger = driver.find_element(By.XPATH, "//*[text()='Day']")
                    driver.execute_script("arguments[0].click();", day_trigger)
                    time.sleep(1)
                    
                    # 随机日期 1-28 (保守起见，避免大小月问题)
                    rand_day = str(random.randint(1, 28))
                    # log(f"随机选择日期: {rand_day}")
                    
                    # 在下拉列表中选择
                    # 避免匹配到其他文本，尽量精确
                    day_opt = driver.find_element(By.XPATH, f"//div[text()='{rand_day}'] | //li[text()='{rand_day}'] | //span[text()='{rand_day}']")
                    driver.execute_script("arguments[0].click();", day_opt)
                except Exception as e:
                    # log(f"点击 Day 失败，尝试键盘流: {e}")
                    actions.send_keys(Keys.TAB).perform()
                    time.sleep(0.2)
                    actions.send_keys(Keys.ENTER).perform()
                    time.sleep(0.2)
                    actions.send_keys(Keys.DOWN).perform() # 选第1个
                    actions.send_keys(Keys.DOWN).perform() # 选第2个
                    actions.send_keys(Keys.ENTER).perform()

                # --- 4. 提交 ---
                time.sleep(1)
                # log("尝试点击 Next...")
                
                # 尝试多种定位方式，因为 Next 可能是 div/span 而不是 button
                xpath_candidates = [
                    "//button[contains(text(), 'Next')]",
                    "//div[contains(text(), 'Next')]",
                    "//span[contains(text(), 'Next')]",
                    "//button[@type='submit']",
                    "//*[text()='Next']"
                ]
                
                clicked_next = False
                for xp in xpath_candidates:
                    try:
                        elements = driver.find_elements(By.XPATH, xp)
                        for el in elements:
                            if el.is_displayed():
                                # log(f"找到可见 Next 按钮 ({xp})，点击...")
                                driver.execute_script("arguments[0].click();", el)
                                clicked_next = True
                                break
                    except: pass
                    if clicked_next: break
                
                if not clicked_next:
                    # log("未找到明确的 Next 按钮，尝试键盘 Enter...")
                    actions.send_keys(Keys.ENTER).perform()
                
            except Exception as e:
                log(f"生日填写出错: {e}")

        # 8. 成功判定 (Session 刷新模式)
        log("等待 Session 刷新 (约 30s)...")
        start_wait = time.time()
        found_sess = None
        
        while time.time() - start_wait < 30:
            cookies = driver.get_cookies()
            sess = next((c['value'] for c in cookies if c['name'] == 'sessionid'), None)
            if sess:
                found_sess = sess
                break
            time.sleep(2)
            
        if found_sess:
            log(f"SUCCESS! Session: {found_sess[:10]}...")
            with open(OUTPUT_FILE, "a") as f:
                f.write(f"{email}|{password}|{found_sess}\n")
            return True
        else:
            log("未获取到 Session，注册可能未完成")
            return False

    except Exception as e:
        log(f"错误: {e}")
        return False

# ================= 入口 =================

if __name__ == "__main__":
    # 屏蔽 undetected_chromedriver 的退出报错
    def suppress_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, OSError) and "[WinError 6]" in str(exc_value):
            return
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
    sys.excepthook = suppress_exception

    print(f"[-] 计划注册账号数: {TOTAL_ACCOUNTS}")

    for i in range(TOTAL_ACCOUNTS):
        log(f"=== 开始注册第 {i+1}/{TOTAL_ACCOUNTS} 个账号 ===")
        
        opts = uc.ChromeOptions()
        opts.add_argument("--no-first-run")
        opts.add_argument("--disable-popup-blocking")
        # 每次使用新的用户数据目录，确保环境隔离（可选，如果网站不严格检查指纹，可以直接重启浏览器）
        # opts.add_argument(f"--user-data-dir=./chrome_profile_{i}")
        
        driver = None
        try:
            driver = uc.Chrome(options=opts, suppress_welcome=True)
            if register_one(driver):
                log(f"第 {i+1} 个账号注册成功")
            else:
                log(f"第 {i+1} 个账号注册失败")
        except Exception as e:
            if "[WinError 6]" not in str(e):
                log(f"运行时错误: {e}")
        finally:
            if driver:
                try:
                    driver.quit()
                except OSError: pass
            
        # 账号间稍微等待，避免请求过快
        if i < TOTAL_ACCOUNTS - 1:
            wait_time = random.randint(5, 10)
            log(f"等待 {wait_time} 秒后继续下一个...")
            time.sleep(wait_time)

    print("[*] 所有任务已结束")
