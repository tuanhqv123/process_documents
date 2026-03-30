#!/usr/bin/env python3
"""
Run the PDF processing pipeline.

Usage:
    python run.py "path/to/document.pdf"
    python run.py "path/to/document.pdf" --max-chunk-words 300
"""

import sys
import argparse
from pathlib import Path

# Add api to path
sys.path.insert(0, str(Path(__file__).parent / "api"))

from pipeline import PDFPipeline, PipelineConfig


def main():
    parser = argparse.ArgumentParser(description="Process PDF documents for LLM/RAG")
    parser.add_argument("file", help="Path to PDF file")
    parser.add_argument("--output-dir", default="output", help="Output directory")
    parser.add_argument("--max-chunk-words", type=int, default=400, help="Max words per chunk")
    parser.add_argument("--min-chunk-words", type=int, default=50, help="Min words per chunk")
    parser.add_argument("--no-images", action="store_true", help="Skip image extraction")
    parser.add_argument("--markdown-only", action="store_true", help="Only output markdown")
    parser.add_argument("--preview", action="store_true", help="Preview first 2000 chars")

    args = parser.parse_args()

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"Error: File not found: {file_path}")
        sys.exit(1)

    config = PipelineConfig(
        max_chunk_words=args.max_chunk_words,
        min_chunk_words=args.min_chunk_words,
        extract_images=not args.no_images,
        output_dir=args.output_dir,
    )

    print(f"\nProcessing: {file_path.name}")
    print("-" * 50)

    pipeline = PDFPipeline(str(file_path), config)
    result = pipeline.run()

    print("-" * 50)

    if args.preview:
        print(f"\n=== MARKDOWN PREVIEW (first 2000 chars) ===\n")
        print(result.markdown[:2000])
        if len(result.markdown) > 2000:
            print(f"\n... ({len(result.markdown) - 2000} more chars)")
        print(f"\n=== CHUNKS PREVIEW ===\n")
        for chunk in result.chunks[:3]:
            print(f"[{chunk.chunk_id}] page {chunk.page_start+1}-{chunk.page_end+1} "
                  f"| {chunk.word_count} words | section: {' > '.join(chunk.section_path) or '(root)'}")
            print(f"  {chunk.text[:150]}...")
            print()
    else:
        # Save outputs
        paths = pipeline.save_output(result)
        print(f"\nDone! {len(result.chunks)} chunks from {result.page_count} pages")


if __name__ == "__main__":
    main()
