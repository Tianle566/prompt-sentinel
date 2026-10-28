# 论文 v2 冻结语料

本目录是原 Apple M1 主实验实际使用的语料副本，逐字节保留原文件。共 1116 条检测样本和 200 条攻击样本；SHA-256 与 `results/thesis_v2_20261022/summary.json` 一致。`manifest.json` 内的旧 Mac 路径是当时的来源记录，不是当前电脑的运行路径。

不要在此目录重建、改标或覆盖样本。日常应用使用 `data/processed/`；两者模板版本可能不同，不能混用后仍声称复核了原论文实验。

Windows 上安装项目依赖后，可不启动模型，直接核对已经保存的预测、回复、CSV 与图表：

```powershell
.\.venv\Scripts\python.exe scripts/audit_results.py results/thesis_v2_20261022 --data-dir data/frozen/thesis_v2_20261022 --report results/my-audit/independent-audit.json
```

每次使用新的报告路径。核对是离线计算，**不重新生成目标回复**，也不等于当前软件在另一台电脑重复得到相同 ASR。重新推理需同时固定对应代码、规则、模型、配置和随机条件，并另建结果目录。

来源、固定 revision、上游文件哈希及抽样说明见 `manifest.json`：

- [deepset/prompt-injections](https://huggingface.co/datasets/deepset/prompt-injections)：使用固定测试划分。
- [THU-COAI/Safety-Prompts](https://github.com/thu-coai/Safety-Prompts)：中文来源安全标签。
- [shibing624/alpaca-zh](https://huggingface.co/datasets/shibing624/alpaca-zh)：按来源视作正常的中文指令。数据卡正文另有非商业研究限制，不仅依据许可元数据判断使用权限。
- 本地模板 v2：构造的编码与间接输入，使用无害测试标记，不代表自然攻击分布。

保留各来源的权利和使用限制；此副本用于本毕业设计研究复核，不包含用户运行日志、账号或真实企业资料。来源标签没有被改写为人工严格注入真值。
