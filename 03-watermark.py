# Historical standalone watermark utility. The maintained report workflow is in 02-upload.py (REQ-23, DEC-24). Direct execution is retired; use the maintained report workflow with an explicit scope.
# Run from the project root; this sharing copy supplies no real student records or working credentials.
import io
import os

from PyPDF2 import PdfReader, PdfWriter
from reportlab.lib.pagesizes import landscape, letter
from reportlab.pdfgen import canvas


def add_header_to_pdf(input_pdf, output_pdf, header_text):
    # Read the existing PDF
    existing_pdf = PdfReader(input_pdf)
    output = PdfWriter()

    for page_num in range(len(existing_pdf.pages)):
        packet = io.BytesIO()

        # Get the page dimensions to decide header placement
        page = existing_pdf.pages[page_num]
        page_width = page.mediabox.width
        page_height = page.mediabox.height

        # Create a canvas with the same size as the PDF page
        if page_width > page_height:
            can = canvas.Canvas(packet, pagesize=landscape(letter))
        else:
            can = canvas.Canvas(packet, pagesize=letter)

        # Draw the header text at an appropriate position
        can.drawString(50, page_height - 25, header_text)
        can.save()

        # Move to the beginning of the BytesIO buffer
        packet.seek(0)
        new_pdf = PdfReader(packet)

        # Merge the two PDFs
        page = existing_pdf.pages[page_num]
        page.merge_page(new_pdf.pages[0])
        output.add_page(page)

    # Write the new PDF
    with open(output_pdf, "wb") as outputStream:
        output.write(outputStream)


def find_pdfs_and_add_header(directory, header_text):
    for root, _, files in os.walk(directory):
        for file in files:
            if file.lower().endswith(".pdf"):
                input_pdf_path = os.path.join(root, file)
                output_pdf_path = os.path.join(root, file)
                add_header_to_pdf(input_pdf_path, output_pdf_path, header_text)
                print(f"Added header to {input_pdf_path}, saved as {output_pdf_path}")


if __name__ == "__main__":
    raise SystemExit(
        "Historical utility retired (DEC-24). Use 02-upload.py report processing "
        "with explicit suffix and header_text."
    )
