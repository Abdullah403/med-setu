"""PDF generation service for MED-SETU referral documents."""
import os
from datetime import datetime

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")


class PDFService:
    """Generate referral PDFs using reportlab (with graceful fallback)."""

    @staticmethod
    def generate_referral_pdf(referral) -> str:
        """Generate a PDF for the referral. Returns file path."""
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        filename = f"referral_{referral.referral_id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.pdf"
        filepath = os.path.join(UPLOAD_DIR, filename)

        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib import colors
            from reportlab.lib.units import mm
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.enums import TA_CENTER

            doc = SimpleDocTemplate(filepath, pagesize=A4,
                                     leftMargin=20*mm, rightMargin=20*mm,
                                     topMargin=20*mm, bottomMargin=20*mm)
            styles = getSampleStyleSheet()
            title_style = ParagraphStyle('Title2', parent=styles['Title'], fontSize=18,
                                          spaceAfter=6, alignment=TA_CENTER)
            subtitle_style = ParagraphStyle('Subtitle', parent=styles['Normal'], fontSize=10,
                                             alignment=TA_CENTER, textColor=colors.grey)
            heading_style = ParagraphStyle('Heading', parent=styles['Heading2'], fontSize=13,
                                            spaceAfter=4, spaceBefore=12,
                                            textColor=colors.HexColor('#1a2f4d'))
            normal = styles['Normal']
            bold_style = ParagraphStyle('Bold', parent=normal, fontName='Helvetica-Bold')

            story = []

            # Header
            story.append(Paragraph("MED-SETU", title_style))
            story.append(Paragraph("Inter-Hospital Referral Document", subtitle_style))
            story.append(Spacer(1, 8*mm))

            # Referral meta
            story.append(Paragraph("REFERRAL DETAILS", heading_style))
            ref_data = [
                ["Referral ID:", referral.referral_id],
                ["Date:", referral.created_at.strftime('%Y-%m-%d') if referral.created_at else "N/A"],
                ["Urgency:", referral.urgency.upper()],
                ["Status:", referral.status.upper()],
            ]
            if referral.verification_code:
                ref_data.append(["Verification Code:", referral.verification_code])
            t = Table(ref_data, colWidths=[45*mm, 120*mm])
            t.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ]))
            story.append(t)
            story.append(Spacer(1, 4*mm))

            # Patient info
            pkg = referral.data_package
            if pkg:
                import json
                ps = json.loads(pkg.patient_summary)
                story.append(Paragraph("PATIENT INFORMATION", heading_style))
                pt_data = [
                    ["Name:", ps.get('full_name', 'N/A')],
                    ["Patient ID:", ps.get('patient_id', 'N/A')],
                    ["Age / Gender:", f"{ps.get('age', 'N/A')} / {ps.get('gender', 'N/A')}"],
                    ["Language:", ps.get('preferred_language', 'N/A')],
                ]
                t = Table(pt_data, colWidths=[45*mm, 120*mm])
                t.setStyle(TableStyle([
                    ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, -1), 10),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                ]))
                story.append(t)
                story.append(Spacer(1, 4*mm))

                # Referring facility
                story.append(Paragraph("REFERRING FACILITY", heading_style))
                rf = referral.referring_facility
                rd = referral.referring_doctor
                rf_data = [
                    ["Facility:", rf.name if rf else "N/A"],
                    ["District:", rf.district if rf else "N/A"],
                    ["Doctor:", rd.user.full_name if rd and rd.user else "N/A"],
                    ["Specialization:", rd.specialization if rd else "N/A"],
                ]
                t = Table(rf_data, colWidths=[45*mm, 120*mm])
                t.setStyle(TableStyle([
                    ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, -1), 10),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                ]))
                story.append(t)
                story.append(Spacer(1, 4*mm))

                # Receiving facility
                story.append(Paragraph("RECEIVING FACILITY", heading_style))
                rcf = referral.receiving_facility
                rcd = referral.receiving_doctor
                rcf_data = [
                    ["Facility:", rcf.name if rcf else "N/A"],
                    ["Department:", referral.receiving_department.name if referral.receiving_department else "N/A"],
                ]
                if rcd and rcd.user:
                    rcf_data.append(["Doctor:", rcd.user.full_name])
                if referral.appointment_date:
                    rcf_data.append(["Appointment:", referral.appointment_date.strftime('%Y-%m-%d')])
                t = Table(rcf_data, colWidths=[45*mm, 120*mm])
                t.setStyle(TableStyle([
                    ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, -1), 10),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                ]))
                story.append(t)
                story.append(Spacer(1, 4*mm))

                # Reason
                story.append(Paragraph("REASON FOR REFERRAL", heading_style))
                story.append(Paragraph(referral.reason, normal))
                story.append(Spacer(1, 4*mm))

                # Clinical summary
                cs = json.loads(pkg.clinical_summary)
                story.append(Paragraph("CLINICAL SUMMARY", heading_style))
                cs_data = [
                    ["Chief Complaint:", cs.get('chief_complaint', 'N/A')],
                    ["Duration:", cs.get('duration', 'N/A')],
                    ["Symptoms:", cs.get('symptoms', 'N/A')],
                ]
                if cs.get('red_flag_detected'):
                    cs_data.append(["RED FLAGS:", cs.get('red_flags', '')])
                t = Table(cs_data, colWidths=[45*mm, 120*mm])
                t.setStyle(TableStyle([
                    ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, -1), 10),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                    ('TEXTCOLOR', (-1, -1), (-1, -1), colors.red) if cs.get('red_flag_detected') else
                    ('TEXTCOLOR', (0, 0), (0, 0), colors.black),
                ]))
                story.append(t)
                story.append(Spacer(1, 4*mm))

                # Prescriptions
                rxs = json.loads(pkg.prescription_data)
                if rxs:
                    story.append(Paragraph("PRESCRIPTIONS", heading_style))
                    for i, rx in enumerate(rxs, 1):
                        med_name = rx.get('medication_name') or rx.get('medication') or 'Medication'
                        dosage = rx.get('dosage', '')
                        freq = rx.get('frequency', '')
                        dur = rx.get('duration', '')
                        line = f"{i}. {med_name} {dosage} - {freq}"
                        if dur:
                            line += f" - {dur}"
                        if rx.get('instructions'):
                            line += f" ({rx['instructions']})"
                        story.append(Paragraph(line, normal))
                    story.append(Spacer(1, 4*mm))

                # Documents
                docs = json.loads(pkg.document_references)
                if docs:
                    story.append(Paragraph("ATTACHED DOCUMENTS", heading_style))
                    for doc_item in docs:
                        ocr = " (OCR text available)" if doc_item.get("has_ocr_text") else ""
                        story.append(Paragraph(f"- {doc_item.get('file_name', 'Document')} ({doc_item.get('file_type', 'file')}){ocr}", normal))
                    story.append(Paragraph("Note: Original documents accessible through MED-SETU receiving interface.", 
                                           ParagraphStyle('Note', parent=normal, fontSize=8, textColor=colors.grey)))

            # Footer
            story.append(Spacer(1, 10*mm))
            story.append(Paragraph("Generated by MED-SETU Healthcare Platform", subtitle_style))

            doc.build(story)
            return filepath

        except ImportError:
            # Fallback: write plain text
            with open(filepath.replace('.pdf', '.txt'), 'w', encoding='utf-8') as f:
                if referral.data_package:
                    f.write(referral.data_package.referral_summary)
                else:
                    f.write(f"Referral: {referral.referral_id}\n")
            return filepath.replace('.pdf', '.txt')
