from pathlib import Path
from PyQt6.QtWidgets import QMainWindow
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtCore import QUrl, pyqtSignal
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage, QWebEngineScript

import config
import db_manager

class CustomWebPage(QWebEnginePage):
    def acceptNavigationRequest(self, url, _type, isMainFrame):
        if url.scheme() in ['http', 'https', 'data', 'qrc', 'file', 'blob', 'javascript']:
            return super().acceptNavigationRequest(url, _type, isMainFrame)
        QDesktopServices.openUrl(url)
        return False 

class PopupWindow(QMainWindow):
    def __init__(self, profile):
        super().__init__()
        self.setWindowTitle("Авторизация OAuth")
        self.resize(500, 600)
        self.browser = QWebEngineView()
        self.browser.setPage(CustomWebPage(profile, self.browser))
        self.setCentralWidget(self.browser)

class CustomBrowser(QWebEngineView):
    def __init__(self, profile):
        super().__init__()
        self.setPage(CustomWebPage(profile, self))

    def createWindow(self, _type):
        self.popup = PopupWindow(self.page().profile())
        self.popup.show()
        return self.popup.browser

class LoginWindow(QMainWindow):
    cookies_ready = pyqtSignal(str, bool) # (acc_id, resume_promo_after)

    def __init__(self, acc_id, resume_promo_after=False):
        super().__init__()
        self.acc_id = acc_id
        self.resume_promo_after = resume_promo_after
        self.collected_cookies = {}
        self.auth_done = False

        acc_data = config.ACCOUNTS.get(acc_id, {})
        self.setWindowTitle(f"Авторизация HoYoLAB — {acc_data.get('name', acc_id)}")
        self.resize(850, 650)
        
        profile_dir = str(Path(db_manager.appdata_dir) / f"web_profile_{acc_id}")
        self.profile = QWebEngineProfile(f"hoyo_{acc_id}", self)
        self.profile.setPersistentStoragePath(profile_dir)

        login_str = acc_data.get("login", "").replace("\\", "\\\\").replace('"', '\\"')
        pass_str = acc_data.get("password", "").replace("\\", "\\\\").replace('"', '\\"')
        
        if login_str and pass_str:
            js_code = f"""
            (function() {{
                let filled = false;
                let avatarClicked = false;
                
                const timer = setInterval(() => {{
                    if (window === window.top && !avatarClicked) {{
                        const hasModal = document.querySelector('.mhy-account-flow, iframe[id*="hyv-account-frame"]');
                        if (!hasModal) {{
                            const avatarBtn = document.querySelector('.header-avatar, .mhy-account-flow-login');
                            if (avatarBtn) {{
                                avatarBtn.click();
                                avatarClicked = true;
                            }}
                        }} else {{
                            avatarClicked = true;
                        }}
                    }}

                    if (filled) {{
                        clearInterval(timer);
                        return;
                    }}

                    const pwdInput = document.querySelector('input[type="password"]');
                    if (pwdInput && pwdInput.offsetParent !== null) {{
                        const inputs = Array.from(document.querySelectorAll('input[type="text"], input[name="username"], input[type="email"]'));
                        const userInput = inputs.find(el => el.offsetParent !== null && el !== pwdInput);
                        
                        if (userInput && pwdInput) {{
                            filled = true;
                            clearInterval(timer);

                            setTimeout(() => {{
                                const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                                
                                userInput.focus();
                                nativeSetter.call(userInput, "{login_str}");
                                userInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                userInput.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                
                                pwdInput.focus();
                                nativeSetter.call(pwdInput, "{pass_str}");
                                pwdInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                pwdInput.dispatchEvent(new Event('change', {{ bubbles: true }}));
                            }}, 350);
                        }}
                    }}
                }}, 600);
            }})();
            """
            script = QWebEngineScript()
            script.setSourceCode(js_code)
            script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
            script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
            script.setRunsOnSubFrames(True)
            self.profile.scripts().insert(script)

        self.browser = CustomBrowser(self.profile)
        self.setCentralWidget(self.browser)
        
        self.cookie_store = self.profile.cookieStore()
        self.cookie_store.cookieAdded.connect(self.on_cookie_added)
        self.cookie_store.deleteAllCookies()

        self.browser.setUrl(QUrl("https://www.hoyolab.com/circles"))

    def on_cookie_added(self, cookie):
        name = cookie.name().data().decode('utf-8')
        value = cookie.value().data().decode('utf-8')
        target_cookies = ["ltuid_v2", "ltoken_v2", "account_id_v2", "cookie_token_v2", "account_mid_v2"]
        if name in target_cookies:
            self.collected_cookies[name] = value
            if not self.auth_done:
                if all(k in self.collected_cookies for k in ["ltuid_v2", "ltoken_v2", "cookie_token_v2", "account_id_v2"]):
                    self.auth_done = True
                    config.update_account_cookies(self.acc_id, self.collected_cookies)
                    self.cookies_ready.emit(self.acc_id, self.resume_promo_after)