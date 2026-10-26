"""Keep deployment and evaluation limitations explicit in the shipped README."""
from pathlib import Path


README_PATH = Path(__file__).resolve().parents[2] / "README.md"


def _paragraphs_in(section):
    readme = README_PATH.read_text(encoding="utf-8")
    content = readme.split(section, 1)[1].split("\n## ", 1)[0]
    return content.split("\n\n")


def test_readme_identifies_local_encoded_indirect_data_limitations():
    paragraphs = _paragraphs_in("## 数据与四组实验")
    assert any(
        all(phrase in paragraph for phrase in (
            "数据局限", "`encoded` 与 `indirect`", "本地构造", "并非独立采集的真实攻击分布",
        ))
        for paragraph in paragraphs
    ), "Evaluation documentation must identify both local template families and their sampling limitation"


def test_readme_discloses_openai_base_url_receives_api_key():
    paragraphs = _paragraphs_in("## API、配置与数据")
    assert any(
        all(phrase in paragraph for phrase in (
            "管理员", "`target.provider` 设为 `openai`", "修改 `target.base_url`",
            "`TARGET_API_KEY`", "作为 API 密钥发送到该地址",
        ))
        for paragraph in paragraphs
    ), "Policy documentation must explain that changing the OpenAI endpoint changes the key recipient"


def test_readme_requires_single_worker_for_in_memory_state():
    paragraphs = _paragraphs_in("## 安装与一键启动")
    assert any(
        all(phrase in paragraph for phrase in (
            "金丝雀会话", "登录计数", "任务队列", "单个进程内",
            "必须使用单 worker", "uvicorn 不要加 `--workers`",
        ))
        for paragraph in paragraphs
    ), "Deployment documentation must tie all three in-memory states to the single-worker requirement"
