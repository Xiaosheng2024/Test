import qrcode
import tkinter as tk
from tkinter import messagebox
from datetime import datetime
import win32print  # 获取Windows打印机列表
import io

# 生成二维码并返回图像路径
def generate_qr_code(content):
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(content)
    qr.make(fit=True)

    # 使用内存流保存二维码图像
    img = qr.make_image(fill='black', back_color='white')
    img_bytes = io.BytesIO()
    img.save(img_bytes)
    img_bytes.seek(0)  # 回到流的开始位置
    return img_bytes

# 构建ZPL指令
def build_zpl(part_name, part_number, batch_number, qr_content):
    # 构建ZPL模板，包含LOGO和其他信息
    zpl = f"""
^XA
^CI28  ; 设置为简体中文字符集
^FO10,15
^GFA,393,290,10,
000018T0FFF0FF07FF3807703C00FFF3FFC7FF980E703C00E00381C7079C0E703E00E00700E7018C0C707600FFC700E7018E1C7067003FC60067038E1C70E30001E60067FF863870E3007FC70067FF073871C300FF8700E70E033071FF00E00781E70703F071FF00E003E7C70703E0738100E001FF870381E0738000E000FF0701C1C0770000,::::V040000002R044000002E455AE51E9955400000294012911224054000002920029610240540000029155294102155400K0660007001980200P01O0,:^FS
^FO10,80
^A0,15,15
^FD零件名称: {part_name}^FS
^FO10,120
^A0,15,15
^FD零件号: {part_number}^FS
^FO10,160
^A0,15,15
^FD生产批次: {batch_number}^FS
^FO250,50
^BQN,2,5
^FDLA,{qr_content}^FS
^FO10,200
^A0,15,15
^FD佛吉亚(海宁)^FS
^PQ1,0,1,Y^XZ
"""
    return zpl

# 获取Windows系统中的打印机列表
def get_printer_list():
    printers = win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)
    printer_names = [printer[2] for printer in printers]  # 获取打印机名称
    return printer_names

# 通过Windows打印机队列发送ZPL指令到打印机
def send_to_printer(zpl, printer_name):
    try:
        # 打开打印机
        printer_handle = win32print.OpenPrinter(printer_name)
        
        # 启动打印任务
        win32print.StartDocPrinter(printer_handle, 1, ("ZPL Print Job", None, "RAW"))
        win32print.StartPagePrinter(printer_handle)
        
        # 写入打印数据
        win32print.WritePrinter(printer_handle, zpl.encode())
        
        # 完成打印任务
        win32print.EndPagePrinter(printer_handle)
        win32print.EndDocPrinter(printer_handle)
        win32print.ClosePrinter(printer_handle)

        print("打印任务已发送")
    except Exception as e:
        print(f"打印失败: {e}")
        messagebox.showerror("打印错误", f"打印失败: {e}")

# 获取输入并触发打印操作
def on_print_button_click():
    # 获取输入框内容
    part_name = entry_part_name.get()
    part_number = entry_part_number.get()
    batch_number = entry_batch_number.get()
    quantity = int(entry_quantity.get())

    # 获取选中的打印机名称
    selected_printer = printer_var.get()

    if selected_printer == "请选择打印机":
        messagebox.showerror("选择错误", "请选择一个打印机进行打印！")
        return

    # 循环打印标签，根据数量递增批次号
    for i in range(quantity):
        current_batch_number = f"{int(batch_number) + i:010d}"  # 批次号递增，确保批次号为10位
        qr_content = f"{part_number}_{current_batch_number}"  # 二维码内容由零件号和批次号组成

        # 生成二维码
        qr_img = generate_qr_code(qr_content)

        # 构建ZPL指令
        zpl = build_zpl(part_name, part_number, current_batch_number, qr_content)

        # 连接打印机并发送ZPL指令
        send_to_printer(zpl, selected_printer)

# 创建GUI窗口
root = tk.Tk()
root.title("简易标签打印程序")

# 设置默认值
default_values = {
    "part_name": "左前门装饰板总成-白色",
    "part_number": "X03-50110014l4lA08",
    "batch_number": "2501160001",
    "quantity": 1
}

# 获取已安装的打印机列表
printer_list = get_printer_list()

# 创建输入框和标签
label_part_name = tk.Label(root, text="零件名称:")
label_part_name.grid(row=0, column=0)
entry_part_name = tk.Entry(root)
entry_part_name.grid(row=0, column=1)
entry_part_name.insert(0, default_values["part_name"])

label_part_number = tk.Label(root, text="零件号:")
label_part_number.grid(row=1, column=0)
entry_part_number = tk.Entry(root)
entry_part_number.grid(row=1, column=1)
entry_part_number.insert(0, default_values["part_number"])

label_batch_number = tk.Label(root, text="生产批次:")
label_batch_number.grid(row=2, column=0)
entry_batch_number = tk.Entry(root)
entry_batch_number.grid(row=2, column=1)
entry_batch_number.insert(0, default_values["batch_number"])

label_quantity = tk.Label(root, text="数量:")
label_quantity.grid(row=3, column=0)
entry_quantity = tk.Entry(root)
entry_quantity.grid(row=3, column=1)
entry_quantity.insert(0, default_values["quantity"])

# 创建打印机选择下拉框
label_printer = tk.Label(root, text="选择打印机:")
label_printer.grid(row=4, column=0)
printer_var = tk.StringVar(root)
printer_var.set("请选择打印机")  # 设置默认值
printer_menu = tk.OptionMenu(root, printer_var, *printer_list)
printer_menu.grid(row=4, column=1)

# 创建打印按钮
print_button = tk.Button(root, text="打印", command=on_print_button_click)
print_button.grid(row=5, column=0, columnspan=2)

# 启动GUI
root.mainloop()
