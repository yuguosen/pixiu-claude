"""定时任务定义"""

import schedule
from rich.console import Console

console = Console()


def setup_daily_schedule():
    """设置每日定时任务

    在交易日 15:30 后运行完整分析流程
    """
    from src.main import cmd_daily

    schedule.every().monday.at("15:45").do(lambda: cmd_daily([]))
    schedule.every().tuesday.at("15:45").do(lambda: cmd_daily([]))
    schedule.every().wednesday.at("15:45").do(lambda: cmd_daily([]))
    schedule.every().thursday.at("15:45").do(lambda: cmd_daily([]))
    schedule.every().friday.at("15:45").do(lambda: cmd_daily([]))

    console.print("[green]定时任务已设置: 工作日 15:45 自动执行日常分析[/]")


def run_scheduler():
    """启动调度器（阻塞模式）"""
    import time

    setup_daily_schedule()
    console.print("[dim]调度器运行中，按 Ctrl+C 退出...[/]")

    try:
        while True:
            schedule.run_pending()
            time.sleep(60)
    except KeyboardInterrupt:
        console.print("\n[yellow]调度器已停止[/]")
