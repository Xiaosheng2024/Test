# EHX 下线防错程序

当前阶段已完成基于客户 Excel 模板的 A5 横向下线单 PDF 生成模块。根目录模板
`报交下线单模板.xlsx` 始终只读，程序只在临时目录处理模板副本。

同时已提供可运行的 PySide6 全屏扫码程序，包含 SQLite 追溯、物料动态导入、
重复/混料/格式防错、满箱生成 PDF、自动打印、失败恢复、历史查询和补打入口。

## 正式部署架构

### Windows 现场

1. 程序使用 ReportLab 编码规则和 Pillow 生成 Code128 PNG，不依赖条码字体。
2. openpyxl 将 PNG 嵌入 Excel 模板副本，保留合并单元格、打印区域、页边距和
   A5 横向设置。
3. Microsoft Excel COM 使用 `ExportAsFixedFormat` 导出 PDF 留档。
4. Microsoft Excel COM 使用 `PrintOut` 直接打印同名 XLSX。
5. Excel COM 失败时可用 ReportLab fallback 生成简化 PDF；失败数据和文件保留，
   可从历史记录补打。

### macOS 开发环境

macOS 只用于代码开发和逻辑验证，直接使用 ReportLab fallback。Mac 不验收正式
Excel 模板转换效果和真实打印效果。

Windows 才是正式 Excel 模板、打印区域、A5 横向和物理打印验收环境。

## 安装

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Windows 正式环境只要求已安装 Microsoft Excel、Python 依赖和打印机驱动，不要求
安装 LibreOffice、SumatraPDF 或 Code128 字体。

## config.json

```json
{
  "printer_name": "",
  "scanner_mode": "serial",
  "serial_port": "",
  "serial_baudrate": 9600,
  "hid_force_english": true,
  "hid_capture_without_input_focus": true,
  "template_path": "报交下线单模板.xlsx",
  "output_pdf_dir": "output/pdf",
  "database_path": "data/ehx_guard.db",
  "reserved1_sub": "2918",
  "box_scan_count": 44,
  "line_name": "EHX",
  "station_name": "下线工位",
  "material_excel_path": "EHX物料号匹配.xlsx",
  "mii_enabled": false,
  "mii_base_url": "https://wwvcamii0071.dc.ege.ds:50001/XMII/",
  "mii_token": "",
  "mii_transaction": "SC_AUTOMATION/API/PRODUCTION/V1/TRANSACTION/PRODUCTION_API",
  "mii_output_parameter": "ResultXML",
  "mii_login_name": "",
  "mii_login_password": "",
  "mii_plant": "",
  "mii_user_id": "",
  "mii_customer_code": "",
  "mii_production_version": "0001",
  "mii_production_shift": "",
  "mii_workcenter": "",
  "mii_packaging_material": "",
  "mii_information_mode": "offline_order_no",
  "mii_information": "",
  "mii_produce_reverse": "P",
  "mii_content_type": "text/xml",
  "mii_timeout_seconds": 10,
  "mii_min_retry_interval_seconds": 60,
  "mii_max_retry_count": 3,
  "barcode_mode": "image",
  "barcode_show_text": true,
  "barcode_output_dir": "output/barcodes",
  "pdf_renderer": "excel_com",
  "print_method": "excel_com",
  "debug_no_print_on_mac": true,
  "mac_pdf_renderer": "reportlab",
  "windows_pdf_renderer": "excel_com",
  "windows_print_method": "excel_com"
}
```

`reserved1_sub` 对应模板占位符 `$Reserved1Sub$`，含义是公司名字代码，默认固定
为 `2918`。它与物料条码无关，不会改变 `5664620-CLBK06` 等物料前缀。客户后续
变更公司代码时，只需修改 `config.json`。

`printer_name` 为空时使用 Windows 默认打印机。
也可在主界面右上角点击“设置”，选择打印机后立即生效。

指定打印机时，必须填写 Windows 打印机列表中的完整名称，例如：

```json
"printer_name": "HP LaserJet MFP M132snw"
```

可在 Windows PowerShell 中查询完整名称：

```powershell
Get-Printer | Select-Object Name
```

正式打印由 Excel COM 调用工作表 `PrintOut`：

- `printer_name` 为空：`worksheet.PrintOut()`
- `printer_name` 非空：`worksheet.PrintOut(ActivePrinter=printer_name)`

如果指定打印机不存在或打印失败，PDF、同名 XLSX 和数据库记录都会保留，订单状态
记为 `PRINT_FAILED`，界面弹出失败原因，可在历史记录中补打。

默认 `barcode_mode=image`。程序生成并嵌入 PNG，`barcode_show_text` 控制条码图片
下方是否显示明文。旧模板字体方式仅作为兼容备用，可配置为
`"barcode_mode": "font"`。

默认 `pdf_renderer=excel_com`、`print_method=excel_com`。生成 PDF 时会在同一目录
保留同名 XLSX，打印时 Excel COM 直接打开该模板副本并执行 `PrintOut`。

macOS 使用 `mac_pdf_renderer=reportlab` 且
`debug_no_print_on_mac=true`：满箱后生成 PDF、将订单记为 `PDF_ONLY`，界面显示
“PDF已生成，已跳过打印”，随后自动进入下一箱。macOS 不会调用 soffice、Excel
COM 或 Windows 打印。

`box_scan_count` 是每箱需要成功扫描的数量。物料号不写死在程序中，首次启动时
从 `material_excel_path` 导入 SQLite 的 `material_mapping` 表，后续也可以从
数据库维护。

### 物料 Excel 格式

`EHX物料号匹配.xlsx` 使用固定的 A/B/C/D 四列：

| 列 | 含义 | 示例 |
| --- | --- | --- |
| A | 扫码条码的固定物料前缀 | `5664620FA2#01` |
| B | 物料名称 | `主驾座椅背板总成 极夜黑` |
| C | 客户物料号/SAP物料号 | `566462001FA2` |
| D | 每箱数量 | `44` |

A 列直接维护完整扫码条码开头的固定部分。程序使用
`完整扫码条码.startswith(Excel A列物料码)` 识别物料，不在代码中写死前缀。
例如 A 列填写：

```text
5664620FA2#01
```

对应的完整扫码条码可以是：

```text
5664620FA2#01#20260701#0001
```

其中 `#20260701#0001` 是日期和流水号，用于区分单件条码和完整条码重复校验，
不写入物料配置。同一箱防错比较的是 Excel A 列匹配出的物料码。

D 列为空时使用 `config.json` 的 `box_scan_count`。D 列非数字、非整数或小于等于
0 时导入失败，并提示具体 Excel 行号。每箱数量在第一件扫码识别物料时写入当前
下线单，此后物料表数量变化不会修改历史订单。

新箱在首件扫码前显示 `0/--`；识别物料后立即切换为该物料的进度，例如
`1/44`。

程序启动时会同步一次 Excel。运行过程中修改 Excel 后，可点击主界面的
“物料查看 / 重新导入”，导入完成后会显示新增、更新和禁用数量；也可以重启程序
使修改生效。

`mii_enabled` 默认必须为 `false`，不会主动请求 MII。启用后，程序在满箱后按
MII API 报产一次：Excel C 列 `客户物料号/SAP物料号` 作为 `PartNumber`，当前箱
`required_count` 作为 `Quantity`，`Information` 默认填本地下线单号。MII 返回
`Status=PRODUCED` 且包含至少 9 位的 `HUCode` 时视为成功。程序保存完整
`HUCode`，生成 `S + HUCode后9位` 的 S 码，打印到“批次号 / 下线单号”位置及其条码。

主界面不再显示本地内部追溯单号。可在“历史查询 / 补打”中输入完整 HU、
`S+后9位` 或裸后9位，查出该箱全部扫码记录。

右上角“设置”的“MII接口”页可现场保存地址、账号、密码、Plant、
UserId、CustomerCode、Workcenter、生产版本、班次、包装材料和 Information。
`PartNumber` 自动取 Excel C 列，`Quantity` 自动取当前箱数量，
`ProductionDate` 自动取当前时间，请求中 `HUCode` 留空。
设置窗口默认显示“设备”页，MII 默认关闭；只有手动打开“MII接口”页并勾选
“启用整箱 MII 报产”保存后，满箱才会请求 MII。

MII 失败时不会自动连续回拨，也不会打印；当前箱保留为 `MII_FAILED`，日志记录错误，
界面提示失败原因。人工重试受 `mii_min_retry_interval_seconds` 和
`mii_max_retry_count` 限制，避免冲击 MII 服务器。

## 启动扫码程序

```powershell
python main.py
```

程序启动后自动全屏。右上角“设置”可选择串口或 HID 扫码枪，现场默认为串口模式：

- HID 模式下，扫码枪回车立即触发校验；即使光标不在扫码输入框，只要当前仍在本程序界面内就可接收。Windows 启动和窗口重新激活时会切换英文键盘布局，扫码字符按键码解析，不依赖中文输入法文本。
- 串口模式下，选择 `COM` 端口和波特率。新大陆 NLS-OY20-RF 默认按
  `9600/8/N/1/无流控` 连接。程序支持 CR、LF、CRLF，支持串口拆包和粘包，
  回车、换行和首尾空格不会存入条码。

现有配置字段为 `scanner_mode=hid|serial`、`serial_port=COM3` 和
`serial_baudrate=9600`。为避免出现两套相同配置，不另外增加 `scan_mode` 和 `baudrate`。
如程序提示串口不存在/打开失败，先在 Windows 设备管理器确认 COM 口；
没有 COM 口时检查 NLS-OY20-RF 的 USB 虚拟串口/转串口驱动。

HID 的“无光标接收”范围是本程序窗口。如现场要求切换到其他软件后仍在后台接收，需要另行配置 Windows Raw Input 和扫码枪设备标识，避免把普通键盘误当扫码枪。
`Esc` 或 `Ctrl+Q` 退出程序。

主界面显示：

- 当前物料号和物料名称
- 每箱需扫、已扫和剩余数量
- 最近扫码和错误原因
- 按条码、HU/S码、内部追溯单号或日期查询，以及补打和失败重试入口
- 物料查看、每箱数量和重新导入入口

成功扫码记录使用 SQLite 部分唯一索引约束完整条码，失败尝试仍会保存，因此重复、
混料、未配置和格式错误均可追溯。

## 扫码格式

物料前缀从 Excel 或 `material_mapping` 表动态读取，前缀不写死在程序中。客户新
格式示例：

```text
Excel A列固定前缀 + #yyyyMMdd#4位流水号
```

例如：

```text
Excel A列：5664620FA2#01
完整条码：5664620FA2#01#20260701#0001
```

重复判断使用完整扫码条码；同箱混料判断使用 Excel A 列前缀匹配出的物料码。日期
和流水号后缀不参与物料配置。

程序同时兼容旧格式 `Excel A列前缀 + yyyyMMdd + 3位流水号`。重复判断始终使用
完整扫码条码。

公司代码 `2918` 只填入 `$Reserved1Sub$`，与物料前缀和完整扫码条码无关。

## Windows 打包路径

GitHub Actions 生成的交付包中，程序从 EXE 同级目录读取以下文件：

- `config.json`
- `EHX物料号匹配.xlsx`
- `报交下线单模板.xlsx`

workflow 只把上述文件复制到 `EHX下线防错_Windows` 根目录，不依赖开发电脑的绝对
路径。`config.json` 中的相对路径以 EXE 所在目录为基准解析。

## 本地逻辑测试

以下测试不调用 LibreOffice，也不执行真实打印：

```powershell
python -m unittest tests.test_scanner_service -v
```

测试覆盖正常满箱、重复、混料、未配置、格式错误、不足满箱、重启恢复、PDF失败
保箱、打印失败保留 PDF 和历史查询。

## 运行环境检查

```powershell
python scripts\check_runtime.py
```

诊断结果包括操作系统、Python、三类 PDF 依赖、模板访问权限、输出目录权限、
默认打印机、配置打印机是否存在，以及当前平台的推荐渲染顺序。

如配置文件不在默认位置：

```powershell
python scripts\check_runtime.py --config D:\EHX\config.json
```

## 生成 PDF

准备 JSON 数据后执行：

```powershell
python generate_a5_pdf.py order.json output\pdf\EHX20260629185500.pdf
```

完整字段说明参见 [A5_PDF说明.md](A5_PDF说明.md)。

## Windows 部署与验收步骤

1. 确认 Microsoft Excel 可以正常启动并打开模板。
2. 安装 Python 依赖，其中 Windows 必须安装 `pywin32`。
3. 安装打印机驱动并打印 Windows 测试页。
4. 修改 `config.json` 或在程序右上角“设置”中选择打印机、HID/串口模式、COM 端口和波特率。
5. 运行 `python scripts\check_runtime.py`，确认 Excel COM、pywin32、模板、
   PDF/条码输出目录、SQLite 和打印机检查通过。
6. 启动 EHX 下线防错程序。
7. 扫描一组正常、重复、混料和未配置条码，验证防错提示。
8. 扫满一箱，检查生成的 PDF 为单页 A5 横向且模板字段完整。
9. 检查 Excel COM 是否直接打印 XLSX，并用扫码枪验证纸面条码。
10. 模拟打印失败，确认 PDF 和数据库记录仍保留，再从历史记录执行补打。

额外检查：

- Windows 10/11 64 位，打印机驱动已安装且测试页正常。
- `printer_name` 留空表示默认打印机；填写时必须与 Windows 打印机完整名称一致。
- 程序对 `output/pdf`、`logs`、`data` 和临时目录具有写权限。
- LibreOffice、SumatraPDF、Code128 字体、7-Zip 和 AweSun 均不是程序运行依赖。

## SQLite

程序直接使用 Python SQLite 驱动，不依赖 Navicat 或任何外部数据库管理软件。
人工排查数据时可选装 DB Browser for SQLite，但生产程序不能依赖它运行。
