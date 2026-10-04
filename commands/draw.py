"""#画图 命令：文生图（默认 Pollinations 免费接口，可选智谱 CogView 升级）。

异步流程（不阻塞回复线程）：
  1. 命令函数立刻返回"正在画"提示（走普通文本回复链路）
  2. 后台线程调用 image_gen.generate_image()（约 5~30 秒）
  3. 成功 → ctx.deliver_image(路径) 把图片投递到出箱队列，主线程用 SendFiles 发群
     失败 → ctx.deliver_text(原因) 发一条文本说明
"""
import threading

import image_gen
from .base import command


@command("画图", aliases=("画画", "绘画", "draw"), glue_args=True,
         help="#画图 描述 - AI 画图，如 #画图 一只在月球上打篮球的柴犬")
def cmd_draw(ctx):
    prompt = (ctx.arg or "").strip()
    if not prompt:
        return "画啥呀？用法：#画图 一只在月球上打篮球的柴犬"

    def _worker():
        try:
            path = image_gen.generate_image(prompt)
            print(f" [画图] 生成成功: {path}")
            if ctx.deliver_image:
                ctx.deliver_image(path, caption=f"画好了~")
        except Exception as e:
            print(f" [画图] 生成失败: {e}")
            if ctx.deliver_text:
                ctx.deliver_text(f"画图失败了：{e}")

    threading.Thread(target=_worker, daemon=True).start()
    return f"收到！正在画「{prompt}」，大约十几二十秒，画好直接发群里~"
