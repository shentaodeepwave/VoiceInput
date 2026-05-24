# VoiceInput 线程管理

## 总览

整个程序运行在 **1 个进程**内，包含 **6 条长期线程**（加临时线程）。所有 Qt 组件仅在主线程操作，其他线程通过 PySide6 Signal 将数据异步投递到主线程。

```
┌─────────────────────────────────────────────────────────────┐
│  线程 1: 主线程 (Qt Event Loop)                                │
│                                                             │
│  app.exec() 阻塞于 Qt 事件循环                                  │
│  ├─ 浮窗 / 托盘图标的绘制与交互                                    │
│  ├─ QTimer 驱动的计时器更新 + 信号轮询                              │
│  └─ 响应 Signal 回调: _on_partial / _on_final / _toggle 等     │
└─────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│  线程 2: keyboard 钩子线程 (隐式)                                │
│                                                              │
│  kb.add_hotkey("right ctrl", ...) 创建                        │
│  └─ 监听全局键盘 → 匹配右 Ctrl → _on_hotkey()                    │
│       └─ bridge.toggle.emit()  →  排队到主线程                   │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│  线程 3: PortAudio 回调线程 (隐式)                               │
│                                                              │
│  sd.InputStream 创建, 每 40ms 触发                             │
│  ├─ 读取 640 样本 int16 → append 到 _chunks                    │
│  └─ on_chunk → session.feed(chunk)                            │
│       └─ WebSocket send_binary() 或 缓冲                        │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│  线程 4: WebSocket 连接线程 (daemon, 显式创建)                     │
│                                                              │
│  session.start() 触发, 仅用于建立连接                              │
│  ├─ DNS 解析 + TCP + TLS + WS Upgrade                         │
│  ├─ 成功后: 启动线程 5, 设置 _ready 事件                           │
│  └─ 失败: 记录 _conn_error, 回调 on_error                        │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│  线程 5: ASR 接收线程 (daemon, 显式创建)                           │
│                                                              │
│  _recv_thread = Thread(target=_receiver)                      │
│  ├─ ws.recv() 阻塞读取 (0.5s 超时)                               │
│  ├─ 解析 JSON → _extract_text()                                │
│  └─ on_partial(text, ...) → _on_asr_partial()                 │
│       └─ bridge.partial.emit()  →  排队到主线程                  │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│  线程 6: Enter 钩子线程 (隐式)                                   │
│                                                              │
│  kb.on_press_key("enter", ...) 创建                           │
│  └─ 检测 Enter → 若有待输入文字 → emit do_type                   │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│  临时线程: 粘贴线程 (每次输入时创建, daemon)                         │
│                                                              │
│  Thread(target=_paste) → 保存剪贴板 → Ctrl+V → 恢复剪贴板         │
└──────────────────────────────────────────────────────────────┘
```

## 线程间通信

所有从工作线程到 GUI 的通信都走 Signal 机制:

```
[工作线程]  on_partial(text)  ──直接调用──→  _on_asr_partial(text)
                                               │
                                     bridge.partial.emit(text)
                                               │
                                    ┌──────────┘
                                    ▼
[主线程事件队列]  →  _on_partial(text)  →  float_win.set_text(text)
```

PySide6 的 `Signal.emit()` 是线程安全的: 如果 emit 发生在非接收者线程，它会自动将调用序列化到接收者 (主线程) 的事件队列中。

## 录音启动时序

按右 Ctrl 后的完整非阻塞流程:

```
时间线 →

0ms     右 Ctrl 按下
        │
0ms     浮窗立即显示 (主线程)
        录音立即开始 (线程 3, audio 先缓冲)
        托盘图标变为录音状态
        │
0ms     WebSocket 连接启动 (线程 4, 后台异步)
        │
        │  音频数据持续进入 feed(), 暂存于 _pending_chunks 列表
        │  GIL + _lock 保证 _pending_chunks 的线程安全
        │
~2s     WebSocket 连接成功
        │  _ready.set()
        │  启动接收线程 (线程 5)
        │  feed() 下一帧时: 先 flush _pending_chunks, 再正常发送
        │
        录音持续, ASR 结果实时回传
        │
用户松键  右 Ctrl 再次按下
        │
        finish() → wait _ready (最多 10s)
        → 发送 end 消息 → 等待最后结果 → 关闭连接
```

## 关键线程安全点

| 位置 | 保护方式 |
|------|----------|
| `_pending_chunks` 读写 | `threading.Lock` (feed 与 connect 线程) |
| `_ready` 事件 | `threading.Event` — 原子 set/wait |
| Qt GUI 更新 | Signal 自动跨线程排队 |
| WebSocket send | 只有音频回调线程在写入, 单线程访问 |
| `_segments` / `_intermediate_texts` | 仅接收线程 (线程 5) 访问, 无竞争 |
| `AudioRecorder._chunks` | 仅 PortAudio 回调线程 append, GIL 保护 |
