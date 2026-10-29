# 新电脑安装与使用指南

GitHub 仓库包含源代码、论文和已提交的历史实验。模型权重、Python环境、前端依赖、账号数据库与密码保存在本机，不随代码下载。

## Windows 首次使用

1. 安装 Python **3.11**，保留 Python 启动器并勾选加入 PATH；安装 Node.js **20.19+ 或 22.12+**（含 npm），随后重新打开终端。
2. 将完整项目解压到固定目录，例如 `D:\prompt-sentinel`。建议16GB及以上内存、至少12GB可用磁盘空间，无需独立显卡。
3. 双击根目录 `start.bat`，或在项目目录的 PowerShell 执行：

   ```powershell
   .\start.bat
   ```

启动器会安装依赖、官方Ollama、预训练模型并准备数据。窗口会显示当前阶段，首次下载需要能够访问 GitHub、Hugging Face、PyPI 和 npm。网络中断后直接再次运行，会继续补齐依赖和缺失文件；无需删除整个项目。现有完整环境日常无需 `--setup`。

出现“Prompt Sentinel 已就绪”后，保持窗口运行，在这台电脑浏览器打开：

- 应用：<http://127.0.0.1:5173>
- 接口文档：<http://127.0.0.1:8000/docs>
- 模型文件及目标服务状态：<http://127.0.0.1:8000/api/health>

若改过端口，以启动窗口显示的地址为准。首次模型调用包含加载时间，CPU处理会较慢。

## 登录与日常开关

默认管理员用户名为 `admin`，普通用户为 `user`；随机密码在首次后端启动后写入 `.runtime\credentials.json`。在项目目录运行：

```powershell
notepad .\.runtime\credentials.json
```

登录后可在“成员与权限”或普通用户的“个人账号”修改密码。新电脑生成自己的初始密码，旧电脑的账号和日志需要单独备份迁移。不要把密码文件或数据库提交到GitHub。

之后双击 `start.bat` 启动，双击 `stop.bat` 关闭本项目的应用和模型进程，释放内存；模型、数据库、论文和结果仍保留。

## 环境检查与故障定位

```powershell
.\start.bat --check
.\.venv\Scripts\python.exe -X utf8 scripts/doctor.py --json
```

检查不会安装依赖、下载模型、启动服务或写入数据库；会逐项列出缺少的环境和文件及处理办法。它核对依赖版本和文件存在性，不校验权重内容，也不替代真实模型测试。服务未启动时，离线检查仍可通过。

- 找不到 Python：确认安装3.11及启动器，重新打开终端；也支持 PATH 中的 Python3.11。
- 找不到 Node.js 或版本过低：安装符合要求的版本，重新打开终端。
- 下载中断：重跑启动脚本，检查上述官方下载站点能否访问；不要使用非官方 `HF_ENDPOINT`。
- 启动失败：根据窗口当前阶段排查；服务日志在 `.runtime\backend.log`、`frontend.log` 和 `ollama.log`。
- 页面可打开但模型报错：先检查健康状态，再按README“分步安装与模型验收”运行真实模型检查；错误拦截不能当作模型正常工作。

如需复用旧电脑模型，可在项目停止时单独复制完整 `models/`（含manifest和分词器），随后正常启动以导入本机Ollama；不要复制旧 `.venv/` 或 `frontend/node_modules/`。

## macOS / Linux

同样安装Python3.11与符合要求的Node.js，在项目根目录执行：

```bash
chmod +x start.sh
./start.sh --setup
# 日常启动
./start.sh
# 离线检查
./start.sh --check
```

按 Ctrl+C 关闭启动器本次创建的服务。更详细的模型来源、实验协议与功能说明见[README](../README.md)。
