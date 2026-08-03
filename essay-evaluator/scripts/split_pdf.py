#!/usr/bin/env python3
"""
split_pdf.py - 수기 답안지 PDF를 학생 단위 이미지로 분할하는 헬퍼 스크립트
"""

import sys
import os

def split_pdf(pdf_path, output_dir):
    if not os.path.exists(pdf_path):
        print(f"❌ Error: File not found - {pdf_path}")
        sys.exit(1)
        
    os.makedirs(output_dir, exist_ok=True)
    print(f"📄 Splitting PDF '{pdf_path}' into images in '{output_dir}'...")
    
    try:
        from pdf2image import convert_from_path
        images = convert_from_path(pdf_path)
        for i, image in enumerate(images):
            out_file = os.path.join(output_dir, f"student_{i+1:03d}.png")
            image.save(out_file, "PNG")
            print(f"  Saved: {out_file}")
        print(f"✅ Successfully converted {len(images)} pages.")
    except ImportError:
        print("⚠️ pdf2image module not found. Please install it via 'pip install pdf2image pillow'.")
    except Exception as e:
        print(f"❌ Failed to split PDF: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 split_pdf.py <pdf_path> <output_dir>")
        sys.exit(1)
    split_pdf(sys.argv[1], sys.argv[2])
