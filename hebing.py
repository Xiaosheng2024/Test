from setuptools import setup

APP = ['jiacha.py']  # 把 'your_script.py' 替换为你的主程序文件
OPTIONS = {
    'argv_emulation': True,   # 如果你的应用需要支持命令行参数传递，可保留该选项
    # 如果需要包含其他依赖库，可以通过 'packages'、'includes' 等参数指定
}

setup(
    app=APP,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
