"""OCR 子模块：下载微信图片到本地临时目录，用 RapidOCR 提取中文文字。

设计要点（避免阻塞主线程）：
- OCR 引擎懒加载，首次使用时才初始化
- 下载和识别都在调用方的后台线程里执行
- 识别失败 / 引擎不可用时返回空串，由调用方降级为 [图片] 占位
"""
import os
import tempfile

_ocr_engine = None
_TEMP_DIR = os.path.join(tempfile.gettempdir(), "wxbot_ocr")


def get_ocr_engine():
    """懒加载 RapidOCR 引擎；失败返回 None。"""
    global _ocr_engine
    if _ocr_engine is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
            _ocr_engine = RapidOCR()
        except Exception as e:
            print(f" [OCR] 引擎加载失败，图片将仅显示[图片]：{e}")
            _ocr_engine = False
    return _ocr_engine if _ocr_engine is not False else None


def ocr_image(image_path) -> str:
    """对本地图片做 OCR，返回拼接后的纯文本；失败返回空串。"""
    engine = get_ocr_engine()
    if engine is None or not image_path:
        return ""
    try:
        result, _ = engine(str(image_path))
        if not result:
            return ""
        lines = [item[1] for item in result if item and len(item) >= 2 and item[1]]
        return "".join(lines).strip()
    except Exception as e:
        print(f" [OCR] 识别异常: {e}")
        return ""


def download_and_ocr(msg) -> str:
    """从 wxauto 图片消息下载到临时目录并 OCR，返回识别文字。
    失败返回空串。临时图片识别后自动清理。"""
    img_path = None
    try:
        os.makedirs(_TEMP_DIR, exist_ok=True)
        img_path = msg.download(dir_path=_TEMP_DIR)
    except Exception as e:
        print(f" [OCR] 图片下载失败: {e}")
        return ""
    if not img_path:
        return ""
    try:
        text = ocr_image(img_path)
        return text
    finally:
        # 清理临时图片
        try:
            if img_path and os.path.exists(str(img_path)):
                os.remove(str(img_path))
        except Exception:
            pass
