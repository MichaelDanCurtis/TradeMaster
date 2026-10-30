"""Disposable local image/PDF decoder. No network, model, or broker operations."""
import json
import importlib.metadata
import math
from pathlib import Path
import sys
import warnings


def main():
    from PIL import Image, ImageOps
    Image.MAX_IMAGE_PIXELS = 20_000_000
    warnings.simplefilter('error', Image.DecompressionBombWarning)
    source, output = Path(sys.argv[1]), Path(sys.argv[2])
    pages = json.loads(sys.argv[3])
    data = source.read_bytes()
    results = []
    if data.startswith(b'%PDF-'):
        import pypdfium2 as pdfium
        with pdfium.PdfDocument(data) as document:
            count = len(document)
            if count > 500 or any(p > count for p in pages):
                raise ValueError('PDF page selection is outside the document limits')
            for number in pages:
                page = document[number-1]
                try:
                    width, height = page.get_size()
                    if not all(math.isfinite(v) and 1 <= v <= 100000 for v in (width, height)):
                        raise ValueError('Invalid PDF page dimensions')
                    bitmap = page.render(scale=1800/max(width, height))
                    try:
                        image = bitmap.to_pil().convert('RGB')
                        image.thumbnail((1800, 1800), Image.Resampling.LANCZOS)
                        filename = f'page-{number}.png'
                        image.save(output/filename)
                        textpage = page.get_textpage()
                        try:
                            text = textpage.get_text_range(count=min(textpage.count_chars(), 4000))
                        finally:
                            textpage.close()
                        results.append({'page': number, 'file': filename, 'width': image.width,
                            'height': image.height, 'text': text[:4000]})
                    finally:
                        bitmap.close()
                finally:
                    page.close()
        kind, mime = 'pdf_page', 'application/pdf'
    else:
        if pages != [1]:
            raise ValueError('An image has only one page')
        with Image.open(source) as image:
            if image.format not in ('PNG', 'JPEG') or getattr(image, 'n_frames', 1) != 1:
                raise ValueError('Only static PNG and JPEG images are supported')
            mime = 'image/png' if image.format == 'PNG' else 'image/jpeg'
            if image.width*image.height > 20_000_000:
                raise ValueError('Image exceeds the pixel limit')
            image = ImageOps.exif_transpose(image)
            image.thumbnail((1800, 1800), Image.Resampling.LANCZOS)
            image = image.convert('RGBA')
            background = Image.new('RGBA', image.size, 'white')
            background.alpha_composite(image)
            background.convert('RGB').save(output/'page-1.png')
            results.append({'page': 1, 'file': 'page-1.png', 'width': image.width, 'height': image.height, 'text': ''})
        count, kind = 1, 'chart_image'
    (output/'result.json').write_text(json.dumps({'page_count': count, 'kind': kind, 'mime': mime, 'pages': results,
        'versions': {name: importlib.metadata.version(name) for name in ('pillow','pypdfium2')}}))


if __name__ == '__main__':
    main()
