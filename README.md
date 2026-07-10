# 模特资料管理系统（Qt5 桌面版）

这是一个本地离线运行的模特资料管理程序，用于新增、筛选、查看和批量导出模特资料。

## 运行方式

```bash
python3 -m pip install -r requirements.txt
python3 app.py
```

## 打包 Windows 安装版

Windows 安装包需要在 Windows 环境构建。macOS 不能可靠地直接编译 Windows 版 PyQt5 程序。

### 方法一：在 Windows 电脑上打包

1. 安装 Python 3.11。
2. 安装 Inno Setup。
3. 双击运行 `build_windows.bat`，生成便携版程序：

```text
dist\ModelSystem\ModelSystem.exe
```

4. 在项目目录运行下面命令生成安装包：

```bat
iscc installer\ModelSystem.iss
```

安装包会生成在：

```text
release\ModelSystem_Setup_1.0.0.exe
```

### 方法二：用 GitHub Actions 自动打包

把项目上传到 GitHub 后，进入仓库的 Actions 页面，运行 `Build Windows Installer` 工作流。

构建完成后，在 Artifacts 里下载：

- `ModelSystem-Windows-Installer`：Windows 安装包
- `ModelSystem-Windows-Portable`：免安装便携版

## 数据位置

- 数据库：`data/models.sqlite3`
- 图片：`uploads/images`
- 视频：`uploads/videos`
- 默认导出目录：`downloads`

程序不需要 Docker，也不需要浏览器或网络服务。
