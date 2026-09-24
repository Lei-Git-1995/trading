# -*- coding: utf-8 -*-
"""
自动重试任务运行器
用法:
    py -3.11 run_job_retry.py basic_data_daily_job
    py -3.11 run_job_retry.py selection_data_daily_job 2026-09-22
    py -3.11 run_job_retry.py indicators_data_daily_job
通过直连重试, 直到任务成功, 绕开东财间歇性风控。
"""
import os
import sys
import time
import subprocess
import random

MAX_ATTEMPTS = 60
WAIT_BASE = 10


def main():
    if len(sys.argv) < 2:
        print("用法: py -3.11 run_job_retry.py <任务名> [日期...]")
        sys.exit(1)

    job = sys.argv[1]
    if job.endswith('.py'):
        job = job[:-3]
    args = [sys.executable, '-m', 'instock.job.' + job] + sys.argv[2:]

    for attempt in range(1, MAX_ATTEMPTS + 1):
        print(f"\n===== 第 {attempt}/{MAX_ATTEMPTS} 次尝试: {' '.join(args)} =====")
        code = subprocess.call(args)
        if code == 0:
            # 任务返回0不代表成功(脚本吞异常), 检查日志是否记录异常
            print(f"===== 第 {attempt} 次执行结束(code={code}), 请人工核对日志 =====")
            return
        wait = WAIT_BASE + attempt * random.randint(2, 8)
        print(f"执行返回 code={code}, 等待 {wait}s 后重试...")
        time.sleep(wait)

    print("重试次数耗尽, 任务仍未成功, 请检查网络或稍后再试。")
    sys.exit(2)


if __name__ == '__main__':
    main()