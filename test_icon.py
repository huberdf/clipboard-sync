#!/usr/bin/env python3
"""测试菜单栏图标"""
import rumps

class TestApp(rumps.App):
    def __init__(self):
        # 用文字代替emoji
        super().__init__("剪贴板", title="CB")
        self.menu = ["状态: 测试中", None, "退出"]

    @rumps.clicked("退出")
    def quit(self, _):
        rumps.quit_application()

if __name__ == "__main__":
    print("启动测试图标...")
    TestApp().run()
