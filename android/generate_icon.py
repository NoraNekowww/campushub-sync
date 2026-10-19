import os
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

def generate_icons():
    # 2048x2048 超采样画布，保证缩放到 512 / 192 / 144 / 96 / 72 / 48 极其细腻抗锯齿
    W = 2048
    H = 2048
    scale = W / 512.0 # 4.0
    
    # 1. 生成渐变背景
    # 从左上角 天大深蓝 (#002244) 渐变到 右下角 微软沉浸蓝 (#0078D4)
    y_coords, x_coords = np.ogrid[:H, :W]
    proj = (x_coords * 0.75 + y_coords * 0.75) / (W * 1.5)
    proj = np.clip(proj, 0.0, 1.0)
    
    # 颜色梯度: Peiyang Navy (#002855) -> Brand Blue (#005A9E) -> Microsoft Fluent Blue (#0078D4)
    c_start = np.array([0, 38, 85], dtype=np.float32)
    c_mid = np.array([0, 90, 158], dtype=np.float32)
    c_end = np.array([0, 120, 212], dtype=np.float32)
    
    r = np.where(proj < 0.5, 
                 c_start[0] + (c_mid[0] - c_start[0]) * (proj / 0.5),
                 c_mid[0] + (c_end[0] - c_mid[0]) * ((proj - 0.5) / 0.5))
    g = np.where(proj < 0.5, 
                 c_start[1] + (c_mid[1] - c_start[1]) * (proj / 0.5),
                 c_mid[1] + (c_end[1] - c_mid[1]) * ((proj - 0.5) / 0.5))
    b = np.where(proj < 0.5, 
                 c_start[2] + (c_mid[2] - c_start[2]) * (proj / 0.5),
                 c_mid[2] + (c_end[2] - c_mid[2]) * ((proj - 0.5) / 0.5))
                 
    rgb = np.stack([r, g, b], axis=-1).astype(np.uint8)
    bg_img = Image.fromarray(rgb, mode='RGB').convert('RGBA')
    
    # 2. 剪裁 Squircle 圆角底板
    corner_radius = int(112 * scale)
    margin = int(12 * scale)
    mask = Image.new('L', (W, H), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle([margin, margin, W - margin, H - margin], radius=corner_radius, fill=255)
    
    icon = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    icon.paste(bg_img, (0, 0), mask)
    
    # 内边缘微发光轮廓
    stroke_mask = Image.new('L', (W, H), 0)
    stroke_draw = ImageDraw.Draw(stroke_mask)
    stroke_width = int(5 * scale)
    stroke_draw.rounded_rectangle([margin, margin, W - margin, H - margin], radius=corner_radius, outline=255, width=stroke_width)
    stroke_layer = Image.new('RGBA', (W, H), (255, 255, 255, 40))
    icon.paste(stroke_layer, (0, 0), stroke_mask)
    
    # 3. 前景色层与阴影层
    fg = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    fg_draw = ImageDraw.Draw(fg)
    
    shadow = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    
    # --- 绘制 TJU 字母 ---
    # 使用 Segoe UI Bold (微软官方标准字体，与 To Do 完美同源)
    font_size = int(148 * scale) # ~592px
    font_path = "C:/Windows/Fonts/segoeuib.ttf"
    if not os.path.exists(font_path):
        font_path = "C:/Windows/Fonts/arialbd.ttf"
    font = ImageFont.truetype(font_path, font_size)
    
    text = "TJU"
    # 获取文字包围盒以精确居中
    bbox = font.getbbox(text)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    
    # 布局定位：上部居中
    text_x = (W - text_w) // 2 - bbox[0]
    text_y = int(92 * scale) - bbox[1]
    
    # 绘制文字阴影
    shadow_offset = int(8 * scale)
    shadow_draw.text((text_x, text_y + shadow_offset), text, font=font, fill=(0, 16, 40, 120))
    # 绘制纯白文字
    fg_draw.text((text_x, text_y), text, font=font, fill=(255, 255, 255, 255))
    
    # --- 绘制 微软对号 (Microsoft Checkmark) ---
    # 放置在 TJU 正下方，留足呼吸间隙，确保与文字完全不产生交叉遮挡
    # 进行视觉重心光学微调（向左微移，匹配长臂视觉重力），线宽提升至 42px 与 TJU 达到 1:1 视觉分量平衡
    shift_x = int(-12 * scale)
    p1 = (int(150 * scale) + shift_x, int(335 * scale))
    p2 = (int(225 * scale) + shift_x, int(410 * scale))
    p3 = (int(360 * scale) + shift_x, int(260 * scale))
    check_w = int(42 * scale) # ~168px 粗细，与 TJU 极粗字重完美匹配
    
    # 对号阴影 (加大圆角弧度，转折点更自然圆润)
    sh_p1 = (p1[0], p1[1] + shadow_offset)
    sh_p2 = (p2[0], p2[1] + shadow_offset)
    sh_p3 = (p3[0], p3[1] + shadow_offset)
    shadow_draw.line([sh_p1, sh_p2, sh_p3], fill=(0, 16, 40, 130), width=check_w, joint="round")
    shadow_draw.ellipse([sh_p1[0] - check_w//2, sh_p1[1] - check_w//2, sh_p1[0] + check_w//2, sh_p1[1] + check_w//2], fill=(0, 16, 40, 130))
    shadow_draw.ellipse([sh_p2[0] - check_w//2, sh_p2[1] - check_w//2, sh_p2[0] + check_w//2, sh_p2[1] + check_w//2], fill=(0, 16, 40, 130))
    shadow_draw.ellipse([sh_p3[0] - check_w//2, sh_p3[1] - check_w//2, sh_p3[0] + check_w//2, sh_p3[1] + check_w//2], fill=(0, 16, 40, 130))
    
    # 对号主体：微软 To Do 经典的实心亮青色发光层 (#38BDF8)
    fg_draw.line([p1, p2, p3], fill=(56, 189, 248, 255), width=check_w, joint="round")
    fg_draw.ellipse([p1[0] - check_w//2, p1[1] - check_w//2, p1[0] + check_w//2, p1[1] + check_w//2], fill=(56, 189, 248, 255))
    fg_draw.ellipse([p2[0] - check_w//2, p2[1] - check_w//2, p2[0] + check_w//2, p2[1] + check_w//2], fill=(56, 189, 248, 255))
    fg_draw.ellipse([p3[0] - check_w//2, p3[1] - check_w//2, p3[0] + check_w//2, p3[1] + check_w//2], fill=(56, 189, 248, 255))
    
    # 对号内芯：饱满纯白高光，与上方的纯白 TJU 形成统一的视觉语言
    inner_w = int(check_w * 0.58)
    fg_draw.line([p1, p2, p3], fill=(255, 255, 255, 245), width=inner_w, joint="round")
    fg_draw.ellipse([p1[0] - inner_w//2, p1[1] - inner_w//2, p1[0] + inner_w//2, p1[1] + inner_w//2], fill=(255, 255, 255, 245))
    fg_draw.ellipse([p2[0] - inner_w//2, p2[1] - inner_w//2, p2[0] + inner_w//2, p2[1] + inner_w//2], fill=(255, 255, 255, 245))
    fg_draw.ellipse([p3[0] - inner_w//2, p3[1] - inner_w//2, p3[0] + inner_w//2, p3[1] + inner_w//2], fill=(255, 255, 255, 245))
    
    # 4. 图层合成
    # 高斯模糊阴影
    shadow_blurred = shadow.filter(ImageFilter.GaussianBlur(radius=int(7 * scale)))
    
    final_canvas = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    final_canvas.paste(icon, (0, 0), icon)
    final_canvas.paste(shadow_blurred, (0, 0), shadow_blurred)
    final_canvas.paste(fg, (0, 0), fg)
    
    # 5. 输出各尺寸图片
    out_512 = final_canvas.resize((512, 512), Image.Resampling.LANCZOS)
    out_512.save('E:/Alpha_nz_Files/campushub-sync/web/public/icons/icon-512.png', 'PNG')
    out_512.save('E:/Alpha_nz_Files/campushub-sync/web/public/icons/icon-512-maskable.png', 'PNG')
    
    out_192 = final_canvas.resize((192, 192), Image.Resampling.LANCZOS)
    out_192.save('E:/Alpha_nz_Files/campushub-sync/web/public/icons/icon-192.png', 'PNG')
    
    out_180 = final_canvas.resize((180, 180), Image.Resampling.LANCZOS)
    out_180.save('E:/Alpha_nz_Files/campushub-sync/web/public/icons/apple-touch-icon.png', 'PNG')
    
    # Android mipmap 各尺寸
    mipmap_configs = [
        ('mipmap-mdpi', 48),
        ('mipmap-hdpi', 72),
        ('mipmap-xhdpi', 96),
        ('mipmap-xxhdpi', 144),
        ('mipmap-xxxhdpi', 192),
    ]
    res_dir = 'E:/Alpha_nz_Files/campushub-sync/android/app/src/main/res'
    for folder, px in mipmap_configs:
        target_dir = os.path.join(res_dir, folder)
        os.makedirs(target_dir, exist_ok=True)
        im = final_canvas.resize((px, px), Image.Resampling.LANCZOS)
        im.save(os.path.join(target_dir, 'ic_launcher.png'), 'PNG')
        im.save(os.path.join(target_dir, 'ic_launcher_round.png'), 'PNG')
        
    out_512.save('E:/Alpha_nz_Files/_preview_icon_512.png', 'PNG')
    print("All icons generated successfully with Segoe UI Bold and Microsoft Checkmark!")

if __name__ == '__main__':
    generate_icons()
