# 缺料汇总生成器

Qt5 图形界面工具，用于把客户导出的缺料报表 Excel 自动生成汇总表。

## 客户使用

1. 双击打开 `缺料汇总生成器.exe`
2. 点击 `选择导入文件`
3. 选择客户导出的 `.xlsx` 文件
4. 点击 `生成汇总表`
5. 程序会在源文件同目录生成：`汇总表_YYYYMMDD.xlsx`

如果当天已存在同名文件，会自动生成：

- `汇总表_YYYYMMDD_01.xlsx`
- `汇总表_YYYYMMDD_02.xlsx`

## GitHub Actions 自动打包

代码推送到 GitHub 后，会自动运行 `.github/workflows/build-windows-exe.yml`。

也可以手动运行：

1. 打开 GitHub 仓库
2. 点击 `Actions`
3. 选择 `Build Windows EXE`
4. 点击 `Run workflow`
5. 构建完成后，在页面底部 `Artifacts` 下载 `缺料汇总生成器_Windows`

## 本地运行源码

```bash
pip install -r requirements.txt
python 缺料汇总生成器_Qt5.py
```

## 本地打包 Windows exe

```bash
pip install -r requirements.txt
pyinstaller --noconsole --onefile --clean --name "缺料汇总生成器" "缺料汇总生成器_Qt5.py"
```

生成文件位置：

```text
dist/缺料汇总生成器.exe
```

## 2026-07-03 修复说明

本版本已去掉 Excel Table 对象，改为普通单元格 + 自动筛选 + 冻结窗格。
原因是部分 Mac/Windows Excel 打开带中文 Sheet 和大量日期列的 Table 对象时，会提示“发现部分内容有问题”，修复后可能只剩 Sheet1。

生成后程序会自动回读校验，确认必须存在 3 个 Sheet：

- 原始数据
- 白夜班
- 一整天
