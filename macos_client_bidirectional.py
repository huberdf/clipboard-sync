"""
macOS 剪贴板双向同步客户端 (增强版)
功能：
1. 接收服务器推送的剪贴板内容 -> 写入本地剪贴板
2. 监控本地剪贴板变化 -> 上传到服务器
3. 菜单栏图标显示连接状态 (绿色=已连接, 红色=断开, 黄色=重连中)
4. 自动重连和错误恢复机制
5. 通知提示连接状态变化

依赖: pip3 install websockets pyperclip rumps

运行方式:
- 命令行: python3 macos_client_bidirectional.py [服务器IP]
- 带菜单栏图标: python3 macos_client_bidirectional.py --gui [服务器IP]
"""
import asyncio
import json
import sys
import time
import threading
import subprocess
import queue  # 添加队列支持
from datetime import datetime
import os

# ============ 配置 ============
SERVER_IP = "8.146.198.121"    # 默认服务器IP
SERVER_PORT = "8000"           # 默认端口
CLIENT_SECRET = "your-secret-key" # 默认密钥
CHECK_INTERVAL = 0.5           # 剪贴板检查间隔(秒)
RECONNECT_DELAY = 5            # 重连延迟(秒)
MAX_RECONNECT_ATTEMPTS = 0     # 最大重连次数 (0=无限)
# ==============================

# 连接状态
class ConnectionState:
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"

current_state = ConnectionState.DISCONNECTED
state_lock = threading.Lock()
gui_app = None  # GUI应用实例

def log(msg):
    """日志输出"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def set_state(new_state):
    """设置连接状态并更新图标"""
    global current_state
    with state_lock:
        if current_state != new_state:
            current_state = new_state
            log(f"状态变更: {new_state}")
            if gui_app:
                gui_app.update_state(new_state)

def get_clipboard():
    """安全获取剪贴板内容 - 优先使用 pbpaste"""
    try:
        # macOS 上 pbpaste 更可靠
        result = subprocess.run(['pbpaste'], capture_output=True, text=True, timeout=2)
        if result.returncode == 0:
            return result.stdout
    except Exception as e:
        pass

    # 备用方案：pyperclip
    try:
        import pyperclip
        return pyperclip.paste()
    except Exception as e:
        log(f"获取剪贴板失败: {e}")
        return None

def set_clipboard(text):
    """安全设置剪贴板内容"""
    try:
        import pyperclip
        pyperclip.copy(text)
        return True
    except Exception as e:
        # 尝试使用pbcopy作为备用方案
        try:
            process = subprocess.Popen(['pbcopy'], stdin=subprocess.PIPE)
            process.communicate(text.encode('utf-8'))
            return True
        except:
            log(f"设置剪贴板失败: {e}")
            return False

async def clipboard_sync():
    """主同步循环"""
    global SERVER_URL
    SERVER_URL = f"ws://{SERVER_IP}:{SERVER_PORT}/ws/client"

    last_clipboard = ""
    reconnect_count = 0

    # 初始化剪贴板
    try:
        last_clipboard = get_clipboard() or ""
        log("剪贴板监控已启动")
    except Exception as e:
        log(f"初始化剪贴板失败: {e}")

    while True:
        try:
            set_state(ConnectionState.CONNECTING)
            log(f"连接服务器: {SERVER_URL}")

            import websockets
            async with websockets.connect(
                SERVER_URL,
                extra_headers={"Authorization": f"Bearer {CLIENT_SECRET}"},
                ping_interval=20,  # 保活ping
                ping_timeout=10,
                close_timeout=5
            ) as ws:
                set_state(ConnectionState.CONNECTED)
                reconnect_count = 0  # 重置重连计数
                log("已连接! 开始双向同步...")

                # 发送通知
                send_notification("剪贴板同步", "已连接到服务器")

                async def receive():
                    nonlocal last_clipboard
                    async for message in ws:
                        try:
                            data = json.loads(message)
                            if data.get("type") == "clipboard":
                                text = data.get("text", "")
                                if text and text != last_clipboard:
                                    if set_clipboard(text):
                                        last_clipboard = text
                                        log(f"[收到] 已写入剪贴板 ({len(text)} 字符)")
                        except json.JSONDecodeError:
                            log("收到无效JSON数据")
                        except Exception as e:
                            log(f"处理消息失败: {e}")

                async def send():
                    nonlocal last_clipboard
                    consecutive_errors = 0
                    while True:
                        try:
                            current = get_clipboard()
                            if current is not None:
                                consecutive_errors = 0
                                if current and current != last_clipboard:
                                    last_clipboard = current
                                    await ws.send(json.dumps({
                                        "type": "clipboard",
                                        "text": current,
                                        "source": "macos"
                                    }))
                                    log(f"[上传] 已发送剪贴板 ({len(current)} 字符)")
                            else:
                                consecutive_errors += 1
                                if consecutive_errors >= 5:
                                    log("连续获取剪贴板失败，尝试恢复...")
                                    consecutive_errors = 0
                                    await asyncio.sleep(2)
                        except Exception as e:
                            log(f"发送失败: {e}")
                        await asyncio.sleep(CHECK_INTERVAL)

                async def heartbeat():
                    """心跳检测"""
                    while True:
                        try:
                            pong = await ws.ping()
                            await asyncio.wait_for(pong, timeout=10)
                        except asyncio.TimeoutError:
                            log("心跳超时，断开连接")
                            set_state(ConnectionState.DISCONNECTED)  # 立即更新状态
                            await ws.close()
                            break
                        except Exception as e:
                            log(f"心跳失败: {e}")
                            set_state(ConnectionState.DISCONNECTED)  # 立即更新状态
                            break
                        await asyncio.sleep(30)

                # 并发执行
                await asyncio.gather(receive(), send(), heartbeat())

        except asyncio.CancelledError:
            log("同步任务被取消")
            break
        except Exception as e:
            set_state(ConnectionState.DISCONNECTED)
            reconnect_count += 1

            if MAX_RECONNECT_ATTEMPTS > 0 and reconnect_count > MAX_RECONNECT_ATTEMPTS:
                log(f"超过最大重连次数 ({MAX_RECONNECT_ATTEMPTS})，停止重连")
                send_notification("剪贴板同步", "连接失败，已停止重连")
                break

            delay = min(RECONNECT_DELAY * (1.5 ** min(reconnect_count - 1, 5)), 60)
            log(f"连接断开: {e}")
            log(f"第 {reconnect_count} 次重连，{delay:.1f}秒后重试...")

            if reconnect_count == 1:
                send_notification("剪贴板同步", "连接断开，正在重连...")

            await asyncio.sleep(delay)

def send_notification(title, message):
    """发送macOS通知"""
    try:
        script = f'display notification "{message}" with title "{title}"'
        subprocess.run(['osascript', '-e', script], capture_output=True, timeout=5)
    except:
        pass

# ============ GUI 菜单栏应用 ============
class ClipboardSyncApp:
    """macOS菜单栏应用"""

    def __init__(self):
        try:
            import rumps
            self.rumps = rumps
        except ImportError:
            log("错误: 需要安装rumps库来显示菜单栏图标")
            log("请运行: pip3 install rumps")
            sys.exit(1)

        # 状态图标路径
        icon_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'icons')
        self.icons = {
            ConnectionState.CONNECTED: os.path.join(icon_dir, 'connected.png'),
            ConnectionState.CONNECTING: os.path.join(icon_dir, 'connecting.png'),
            ConnectionState.DISCONNECTED: os.path.join(icon_dir, 'disconnected.png')
        }

        self.app = rumps.App(
            "剪贴板同步",
            icon=self.icons[ConnectionState.DISCONNECTED],
            quit_button=None
        )

        # 菜单项
        self.status_item = rumps.MenuItem("状态: 未连接")
        self.status_item.set_callback(None)

        self.server_item = rumps.MenuItem(f"服务器: {SERVER_IP}:{SERVER_PORT}")
        self.server_item.set_callback(None)

        self.reconnect_item = rumps.MenuItem("立即重连", callback=self.reconnect)
        self.quit_item = rumps.MenuItem("退出", callback=self.quit_app)

        self.app.menu = [
            self.status_item,
            self.server_item,
            None,  # 分隔线
            self.reconnect_item,
            None,
            self.quit_item
        ]

        self.sync_thread = None
        self.loop = None
        
        # 状态更新队列 - 用于线程间通信
        self.state_queue = queue.Queue()
        
        # 定时器 - 在主线程中检查队列并更新 UI
        @rumps.timer(0.5)  # 每0.5秒检查一次
        def check_state_queue(_):
            self._check_state_queue()
        self._state_timer = check_state_queue

    def _check_state_queue(self):
        """在主线程中检查队列并更新 UI (由 Timer 调用)"""
        try:
            # 非阻塞获取最新状态
            state = None
            while not self.state_queue.empty():
                state = self.state_queue.get_nowait()
            
            if state is not None:
                new_icon = self.icons.get(state)
                if new_icon and os.path.exists(new_icon):
                    self.app.icon = new_icon

                status_text = {
                    ConnectionState.CONNECTED: "状态: 已连接 ✓",
                    ConnectionState.CONNECTING: "状态: 连接中...",
                    ConnectionState.DISCONNECTED: "状态: 未连接"
                }
                self.status_item.title = status_text.get(state, "状态: 未知")
                log(f"[GUI-主线程] 图标已更新: {state}")
        except Exception as e:
            log(f"[GUI] 检查队列失败: {e}")

    def update_state(self, state):
        """更新菜单栏状态 (线程安全 - 通过队列传递到主线程)"""
        log(f"[GUI] 状态入队: {state}")
        self.state_queue.put(state)

    def reconnect(self, _):
        """手动触发重连"""
        log("用户请求重连...")
        # 重启同步线程
        self.start_sync()

    def quit_app(self, _):
        """退出应用"""
        log("正在退出...")
        if self.loop:
            self.loop.call_soon_threadsafe(self.loop.stop)
        self.rumps.quit_application()

    def start_sync(self):
        """启动同步线程"""
        def run_sync():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            try:
                self.loop.run_until_complete(clipboard_sync())
            except Exception as e:
                log(f"同步线程异常: {e}")
            finally:
                self.loop.close()

        if self.sync_thread and self.sync_thread.is_alive():
            log("同步线程正在运行")
            return

        self.sync_thread = threading.Thread(target=run_sync, daemon=True)
        self.sync_thread.start()

    def run(self):
        """运行应用"""
        global gui_app
        gui_app = self

        log("=" * 50)
        log("macOS 剪贴板双向同步客户端 (GUI模式)")
        log(f"服务器: {SERVER_IP}:{SERVER_PORT}")
        log("菜单栏图标说明:")
        log("  🟢 = 已连接")
        log("  🟡 = 连接中")
        log("  🔴 = 未连接")
        log("=" * 50)

        self.start_sync()
        self.app.run()

# ============ 命令行模式 ============
def run_cli():
    """命令行模式运行"""
    log("=" * 50)
    log("macOS 剪贴板双向同步客户端")
    log(f"服务器: {SERVER_IP}:{SERVER_PORT}")
    log("提示: 使用 --gui 参数启动菜单栏图标模式")
    log("=" * 50)

    try:
        asyncio.run(clipboard_sync())
    except KeyboardInterrupt:
        log("用户中断，退出")

# ============ 主入口 ============
if __name__ == "__main__":
    gui_mode = False

    # 解析命令行参数
    args = sys.argv[1:]
    for arg in args:
        if arg == "--gui" or arg == "-g":
            gui_mode = True
        elif not arg.startswith("-"):
            SERVER_IP = arg

    if gui_mode:
        app = ClipboardSyncApp()
        app.run()
    else:
        run_cli()
