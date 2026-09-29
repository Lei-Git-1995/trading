chcp 65001
@echo off
:: 计划任务专用：交易日开盘前运行，自动保存上一个交易日的数据（不要在盘中运行）
cd /d %~dp0
cd ..
cd job
echo %date% %time% 开始执行 >> ..\log\run_job_daily.log
py -3.11 execute_daily_job.py >> ..\log\run_job_daily.log 2>&1
echo %date% %time% 执行结束 >> ..\log\run_job_daily.log
exit
