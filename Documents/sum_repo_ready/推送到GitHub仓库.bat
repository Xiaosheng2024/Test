@echo off
chcp 65001 >nul
set REPO_URL=https://github.com/Xiaosheng2024/sum.git

cd /d %~dp0

echo 初始化 Git 仓库...
git init

echo 设置分支 main...
git branch -M main

echo 添加远程仓库...
git remote remove origin 2>nul
git remote add origin %REPO_URL%

echo 提交文件...
git add .
git commit -m "Add Qt5 shortage summary generator and Windows EXE workflow"

echo 推送到 GitHub...
git push -u origin main

echo 完成。打开 GitHub Actions 查看打包结果。
pause
