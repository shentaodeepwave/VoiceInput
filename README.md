# 🎙️ VoiceInput - 桌面语音输入助手
> 七牛云 × XEngineer 暑期实训营 · 72小时极速开发
demo视频链接：https://www.bilibili.com/video/BV1GDGo6UEw1/
## 📌 项目简介
**VoiceInput** 是一款桌面语音输入工具，以**迷你悬浮窗**形式常驻桌面。  
按下 **F2** 或单击麦克风即可开始语音转文字，识别结果**实时流式**显示，并自动填入当前光标所在位置。  
支持**历史记录**、**VAD 静音检测**等特性，让你彻底解放双手。
## ✨ 核心功能
- 🎤 **一键录音**：单击麦克风按钮或按 `F2` 开始/停止录音（支持自定义快捷键）
- 📝 **流式实时转写**：边说边出字，无需等待
- 📜 **识别历史记录**：自动保存最近 3 条结果，每条支持一键复制或删除
- ⚡ **VAD 静音自动停止**：可自定义静音延迟，适应不同语速
- 🖱️ **点按/长按双模式**：默认点按（单击开始/停止），也支持长按说话模式
- 🔒 **系统托盘**：最小化到托盘，后台静默运行
- 🎨 **亮色小清新悬浮窗**：始终置顶，可拖动，录音时自适应变高
## 🖥️ 技术栈
| 模块 | 技术 |
|------|------|
| 桌面 GUI | Python + PySide6（Qt for Python） |
| 语音识别 | 讯飞实时语音转写（WebSocket 流式） |
| 音频采集 | sounddevice（16kHz / mono / int16） |
| 全局快捷键 | keyboard 库 |
| 配置存储 | YAML 文件 + 环境变量 |
## 👥 团队分工
| 角色 | 负责内容 |
|------|----------|
| **WELT** — 产品经理 | 需求分析、PRD、UI/交互文档、测试用例、演示脚本、README、部分前端 |
| **DeepWave** — 开发工程师 | 音频采集、讯飞 API 集成、流式识别、VAD、托盘与快捷键、程序打包 |
## 🚀 快速开始
可以直接下载最新发行版（0.13）体验或者↓
### 环境要求
- Windows 10/11（macOS 理论可用，未充分测试）
- Python 3.9+
- 麦克风设备
### 安装与运行
```bash
# 克隆仓库
git clone https://github.com/shentaodeepwave/VoiceInput.git
cd VoiceInput
# 创建虚拟环境（推荐）
python -m venv venv
venv\Scripts\activate      # Windows
# source venv/bin/activate  # macOS
# 安装依赖
pip install -r voiceinput/requirements.txt
# 启动（首次运行后，在系统托盘 → 设置 中填写讯飞 API 密钥）
python voiceinput/main.py
API 密钥也可通过环境变量 XF_APP_ID、XF_ACCESS_KEY_ID、XF_ACCESS_KEY_SECRET 设置。
📁 项目结构
voiceinput/
├── main.py              # 入口：Qt 应用 + 托盘 + 热键
├── app.py               # 核心控制器：状态机 + 录音 + 识别 + 输出
├── window.py            # 悬浮窗 UI：卡片、按钮、历史面板、自适应高度
├── settings.py          # 设置对话框：API、快捷键、VAD、麦克风测试
├── config.py            # 配置管理：YAML 读写 + 环境变量覆盖
├── audio_capture.py     # 录音：sounddevice 16kHz 单声道采集
├── asr_engine.py        # 讯飞 WebSocket 流式识别引擎
├── vad.py               # 语音活动检测（RMS 能量阈值）
└── requirements.txt     # Python 依赖
🎛️ 使用说明
操作	方式
开始/停止录音	按 F2 或 点击悬浮窗麦克风
查看历史记录	点击悬浮窗右上角时钟图标
复制历史记录	历史面板中点击 ⎘ 按钮
删除历史记录	历史面板中点击 ✕ 按钮
修改快捷键	系统托盘 → 设置
切换点按/长按	系统托盘 → 设置 → 快捷键与模式
退出程序	系统托盘 → 关闭程序
📄 许可证
MIT
