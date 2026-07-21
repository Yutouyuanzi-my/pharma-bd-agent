"""
药企 BD 每日竞品监测简报 —— 自动化邮件推送。

功能：定时抓取 ClinicalTrials.gov 上指定治疗领域的近期变动，
结合竞争格局分析，生成 Markdown 简报并发送到指定邮箱。

依赖（.env，均不硬编码，从环境变量读取）：
    DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL / DEEPSEEK_MODEL   # 已有
    SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASSWORD       # 发件 SMTP（授权码）
    EMAIL_TO                                                 # 收件人（逗号分隔）
    MONITOR_CONDITIONS                                       # 监控领域（逗号分隔）
    MONITOR_SINCE_DAYS                                       # 监测天数，默认 7
    BRIEF_TIME                                               # 每天发送时间，默认 08:00

用法：
    python daily_brief_email.py --once          # 立即跑一次（真正发邮件）
    python daily_brief_email.py --dry-run       # 生成本地预览 HTML，不发送（测试用）
    python daily_brief_email.py                 # 进入定时循环（每天 BRIEF_TIME 发送）
"""

import os
import ssl
import argparse
import smtplib
from datetime import datetime
from typing import Optional
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import markdown
from dotenv import load_dotenv
from openai import OpenAI

from tools import monitor_recent_changes, analyze_competitive_landscape

load_dotenv()


# ── 配置读取（全部来自环境变量 / .env，禁止硬编码密钥）──
def _cfg(key: str, default=None):
    val = os.getenv(key)
    return val if val is not None else default


SMTP_HOST = _cfg("SMTP_HOST")
SMTP_PORT = int(_cfg("SMTP_PORT", "465"))
SMTP_USER = _cfg("SMTP_USER")
SMTP_PASSWORD = _cfg("SMTP_PASSWORD")
EMAIL_TO = [x.strip() for x in (_cfg("EMAIL_TO") or "").split(",") if x.strip()]
CONDITIONS = [x.strip() for x in (_cfg("MONITOR_CONDITIONS") or "").split(",") if x.strip()]
SINCE_DAYS = int(_cfg("MONITOR_SINCE_DAYS", "7"))
BRIEF_TIME = _cfg("BRIEF_TIME", "08:00")
MODEL = _cfg("DEEPSEEK_MODEL", "deepseek-chat")
API_KEY = _cfg("DEEPSEEK_API_KEY")
BASE_URL = _cfg("DEEPSEEK_BASE_URL")

client = OpenAI(api_key=API_KEY, base_url=BASE_URL) if API_KEY else None


def build_brief_markdown(condition: str) -> Optional[str]:
    """为单个治疗领域生成简报 Markdown；若无近期变动返回 None（本次不发送）。"""
    monitor = monitor_recent_changes(condition, since_days=SINCE_DAYS)
    if "error" in monitor:
        return f"## {condition}\n\n⚠️ 数据获取失败：{monitor['error']}\n"

    count = monitor.get("new_and_updated_count", 0)
    if count == 0:
        return None  # 无变动，跳过该领域，避免每日空邮件

    landscape = analyze_competitive_landscape(condition, llm_client=client, model=MODEL)
    summary = landscape.get("llm_summary", "") if "llm_summary" in landscape else ""

    today = datetime.now().strftime("%Y-%m-%d")
    lines = [f"## {condition}（过去 {SINCE_DAYS} 天）", ""]
    lines.append(f"**新增 / 更新试验：{count} 项**")
    lines.append("")
    for s in monitor.get("studies", [])[:15]:
        link = s.get("nct_link") or f"https://clinicaltrials.gov/study/{s.get('nct_id', '')}"
        title = s.get("brief_title", "")[:80]
        sp = s.get("sponsor", "")
        ph = s.get("phase", "")
        stt = s.get("overall_status", "")
        risk = " ".join(s.get("risk_tags", []))
        lines.append(f"- [{title}]({link}) — {sp} · {ph} · {stt} {risk}")
    lines.append("")
    if summary:
        lines.append("### 竞争格局摘要")
        lines.append(summary)
    lines.append("")
    lines.append(f"*生成时间：{today} · 数据来源：ClinicalTrials.gov API v2*")
    return "\n".join(lines)


def run_once(dry_run: bool = False) -> bool:
    """执行一次：生成所有领域的简报并（或预览）发送。返回是否产生内容。"""
    if not client:
        print("[ERROR] 未配置 DEEPSEEK_API_KEY，无法生成简报。")
        return False
    if not CONDITIONS:
        print("[ERROR] 未配置 MONITOR_CONDITIONS。")
        return False
    if not dry_run and not (SMTP_HOST and SMTP_USER and SMTP_PASSWORD and EMAIL_TO):
        print("[ERROR] 未配置 SMTP / 收件人，无法发送邮件（可加 --dry-run 仅生成本地预览）。")
        return False

    sections = []
    for cond in CONDITIONS:
        try:
            md = build_brief_markdown(cond)
            if md:
                sections.append(md)
            else:
                print(f"[INFO] {cond}：无近期变动，跳过。")
        except Exception as e:
            sections.append(f"## {cond}\n\n⚠️ 生成失败：{e}\n")

    if not sections:
        print("[INFO] 所有监控领域均无近期变动，本次不发送邮件。")
        return False

    title = " / ".join(CONDITIONS)
    now = datetime.now()
    subject = f"BD 竞品监测日报 · {title} · {now.strftime('%Y-%m-%d')}"
    body_md = (
        f"# BD 竞品监测日报\n\n"
        f"> 自动生成于 {now.strftime('%Y-%m-%d %H:%M')} · 监控领域：{title}\n\n"
        + "\n\n---\n\n".join(sections)
    )
    html = markdown.markdown(body_md, extensions=["tables", "fenced_code"])

    if dry_run:
        preview_path = os.path.join(os.path.dirname(__file__), "daily_brief_preview.html")
        with open(preview_path, "w", encoding="utf-8") as f:
            f.write(_html_shell(subject, html))
        print(f"[DRY-RUN] 预览已生成：{preview_path}（未发送）")
        return True

    send_email(subject, html)
    return True


def _html_shell(title: str, body_html: str) -> str:
    """给邮件正文套一层基础样式，保证邮箱内可读性。"""
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<style>
  body {{ font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
         line-height: 1.6; color: #222; max-width: 760px; margin: 0 auto; padding: 24px; }}
  h1 {{ font-size: 22px; color: #c05621; }}
  h2 {{ font-size: 18px; border-left: 4px solid #e8965a; padding-left: 10px; margin-top: 28px; }}
  h3 {{ font-size: 15px; color: #444; }}
  a {{ color: #2b6cb0; text-decoration: none; }}
  table {{ border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 13px; }}
  th, td {{ border: 1px solid #e2e2e2; padding: 6px 8px; text-align: left; }}
  blockquote {{ background: #f7f3ee; border-left: 4px solid #e8965a; margin: 12px 0;
               padding: 8px 14px; color: #555; font-size: 13px; }}
</style></head><body>
<h1>{title}</h1>
{body_html}
</body></html>"""


def send_email(subject: str, html: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = ", ".join(EMAIL_TO)
    msg.attach(MIMEText(html, "html", "utf-8"))

    if SMTP_PORT == 465:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ssl.create_default_context()) as s:
            s.login(SMTP_USER, SMTP_PASSWORD)
            s.send_message(msg)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.starttls(context=ssl.create_default_context())
            s.login(SMTP_USER, SMTP_PASSWORD)
            s.send_message(msg)
    print(f"[OK] 邮件已发送至 {', '.join(EMAIL_TO)}：{subject}")


def main():
    parser = argparse.ArgumentParser(description="BD 竞品监测每日简报邮件推送")
    parser.add_argument("--once", action="store_true", help="立即运行一次并退出（真正发邮件）")
    parser.add_argument("--dry-run", action="store_true", help="生成本地预览 HTML，不发送")
    args = parser.parse_args()

    if args.once or args.dry_run:
        run_once(dry_run=args.dry_run)
        return

    # 定时循环（可选依赖 schedule；也可用系统 launchd/cron 调用 --once）
    try:
        import schedule
    except ImportError:
        print("[ERROR] 未安装 schedule 库。请 pip install schedule，"
              "或改用系统定时任务（launchd/cron）调用 `python daily_brief_email.py --once`。")
        return

    hh, mm = BRIEF_TIME.split(":")
    schedule.every().day.at(f"{hh}:{mm}").do(run_once)
    print(f"[INFO] 定时模式启动，每天 {BRIEF_TIME} 发送 BD 简报。Ctrl+C 退出。")
    import time
    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
