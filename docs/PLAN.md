# VoiceInput 最小测试产品计划

## 目标

验证语音输入核心链路：**按键 → 录音 → 识别 → 输出**，命令行形式，不加 GUI。

## 范围

| 包含 | 不包含 |
|------|--------|
| 全局热键触发录音 | 系统托盘 / GUI |
| 音频采集 (16kHz mono) | 设置界面 |
| SenseVoice-Small 识别 | PyInstaller 打包 |
| 控制台打印识别结果 | 独立 VAD 模块 |
| 录音状态提示 | 自动键盘输入 |

## 项目结构

```
voiceinput/
├── main.py              # 入口: 热键循环 → 录音 → 识别 → 打印
├── audio_capture.py     # 录音: sounddevice, 16kHz, 按键松停
├── asr_engine.py        # 识别: SenseVoice-Small 加载 + 推理
└── requirements.txt     # 依赖
```

### main.py

- 使用 pynput 注册全局热键 Ctrl+Shift+V
- 按下 → 打印"录音中..." → 调用录音
- 松键 → 打印"识别中..." → 调用 ASR → 输出结果

### audio_capture.py

- record_while_held(): 按住热键期间录音，松键返回 numpy 数组
- sounddevice.InputStream 实时回调采集
- 采样率 16000，单声道，int16

### asr_engine.py

- 封装 funasr.AutoModel，模型 iic/SenseVoiceSmall
- 单次加载，后续复用，避免反复加载 200MB 模型
- recognize(audio: np.ndarray) -> str 返回识别文本

## 依赖

```
funasr>=1.0.0
sounddevice>=0.4.6
pynput>=1.7.6
numpy>=1.24.0
```

模型首次运行自动从 ModelScope 下载，约 200MB。

## 验收标准

1. 按 Ctrl+Shift+V 开始录音
2. 控制台显示"正在录音..."
3. 松键后 1 秒内打印识别结果
4. 中文短句准确识别
5. 连续多次使用模型不重新加载

## 预计耗时

~2h
