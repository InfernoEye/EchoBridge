"""Produce the EchoBridge Windows icon locally; no font files distributed."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import sys

output = Path(sys.argv[1])
output.parent.mkdir(parents=True, exist_ok=True)
size = 256
img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((13, 13, 243, 243), radius=62, fill=(108, 96, 230, 255))
d.rounded_rectangle((22, 22, 234, 234), radius=55, outline=(147, 138, 250, 240), width=3)
font = None
for candidate in (r'C:\Windows\Fonts\segoeuib.ttf', r'C:\Windows\Fonts\arialbd.ttf'):
    if Path(candidate).exists():
        font = ImageFont.truetype(candidate, 145)
        break
if font is None:
    font = ImageFont.load_default()
d.text((128, 127), 'E', fill='white', font=font, anchor='mm', stroke_width=0)
img.save(output, format='ICO', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
print('Icon created:', output)
