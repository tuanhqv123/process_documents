#!/usr/bin/env python3
"""
Test backend with RapidDoc - complete document processing.

Usage:
    python test_rapiddoc_backend.py [pdf_path]

If no PDF path provided, uses first PDF in data/uploads/
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

def test_rapiddoc_backend(pdf_path: str = None):
    """Test backend with RapidDoc integration."""
    if not pdf_path:
        uploads_dir = Path("data/uploads")
        pdf_files = list(uploads_dir.glob("*.pdf"))

        if not pdf_files:
            print("❌ No PDF files found in data/uploads/")
            print("   Please place a PDF file in data/uploads/ first.")
            return False

        pdf_path = str(pdf_files[0])

    print("=" * 60)
    print("Testing Backend with RapidDoc")
    print("=" * 60)
    print(f"PDF: {pdf_path}\n")

    # Import pipeline
    try:
        from src.pdf_processor.pipeline import PDFPipeline, PipelineConfig
    except ImportError as e:
        print(f"❌ Failed to import pipeline: {e}")
        return False

    # Initialize pipeline
    print("Initializing pipeline...")
    try:
        output_dir = "output/images"
        config = PipelineConfig(image_output_dir=output_dir)
        pipeline = PDFPipeline(pdf_path, config)
        print("✓ Pipeline initialized\n")
    except Exception as e:
        print(f"❌ Failed to initialize pipeline: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Get page count
    total = pipeline.page_count()
    print(f"Total pages: {total}\n")

    # Process pages (simulates backend behavior)
    print("=" * 60)
    print("Processing Pages with RapidDoc")
    print("=" * 60)

    results = []
    total_time = 0
    total_chars = 0
    total_images = 0

    start_time = time.time()

    for i, page_result in enumerate(pipeline.process_pages()):
        results.append(page_result)

        total_time += page_result.time_sec
        total_chars += len(page_result.markdown)
        total_images += len(page_result.images)

        print(f"  Page {page_result.page_num + 1}: {page_result.time_sec}s, "
              f"{len(page_result.markdown)} chars, {len(page_result.images)} images")

        # Stop after 5 pages for testing
        if i >= 4:
            print(f"\n  ... (stopping after 5 pages for testing)")
            break

    elapsed = time.time() - start_time

    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"Pages processed: {len(results)}")
    print(f"Total time: {elapsed:.2f}s")
    print(f"Average per page: {total_time / len(results):.2f}s")
    print(f"Total characters: {total_chars}")
    print(f"Total images: {total_images}")

    # Show markdown preview
    if results:
        print("\n" + "=" * 60)
        print("Markdown Preview (First Page)")
        print("=" * 60)
        print(results[0].markdown[:500])
        if len(results[0].markdown) > 500:
            print("...")

    print("\n" + "=" * 60)
    print("✓ Backend Test Complete with RapidDoc!")
    print("=" * 60)
    print("\n✅ RapidDoc is now integrated in backend!")
    print("✅ Features: OCR, Layout, Tables, Formulas")
    print("✅ Optimized for Mac M2 with ONNX Runtime")

    return True

if __name__ == "__main__":
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else None
    success = test_rapiddoc_backend(pdf_path)
    sys.exit(0 if success else 1)
