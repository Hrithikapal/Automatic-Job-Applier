"""
assets/resumes/generate_resume.py — Generate Alex Chen's demo resume PDF.

Uses reportlab to produce a clean, ATS-friendly single-page PDF.
Called automatically by seed.py if the PDF does not exist.
"""
from __future__ import annotations

import os
from pathlib import Path


def generate_alex_chen_resume(output_path: str = "assets/resumes/alex_chen_resume.pdf") -> str:
    """Generate the demo resume PDF and return the output path."""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.lib import colors
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, HRFlowable
        )
        from reportlab.lib.enums import TA_LEFT, TA_CENTER
    except ImportError:
        print("[Resume] reportlab not installed — skipping PDF generation")
        print("[Resume] Run: pip install reportlab")
        return output_path

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
    )

    styles = getSampleStyleSheet()

    # ── Custom styles ────────────────────────────────────────────────────
    name_style = ParagraphStyle(
        "Name",
        fontSize=22,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#1a1a2e"),
        alignment=TA_CENTER,
        spaceAfter=2,
    )
    contact_style = ParagraphStyle(
        "Contact",
        fontSize=9,
        fontName="Helvetica",
        textColor=colors.HexColor("#444444"),
        alignment=TA_CENTER,
        spaceAfter=8,
    )
    section_style = ParagraphStyle(
        "Section",
        fontSize=11,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#1a1a2e"),
        spaceBefore=10,
        spaceAfter=2,
    )
    job_title_style = ParagraphStyle(
        "JobTitle",
        fontSize=10,
        fontName="Helvetica-Bold",
        textColor=colors.black,
        spaceAfter=1,
    )
    job_meta_style = ParagraphStyle(
        "JobMeta",
        fontSize=9,
        fontName="Helvetica-Oblique",
        textColor=colors.HexColor("#555555"),
        spaceAfter=3,
    )
    bullet_style = ParagraphStyle(
        "Bullet",
        fontSize=9,
        fontName="Helvetica",
        textColor=colors.black,
        leftIndent=12,
        spaceAfter=2,
        leading=13,
    )
    normal_style = ParagraphStyle(
        "NormalSmall",
        fontSize=9,
        fontName="Helvetica",
        textColor=colors.black,
        spaceAfter=3,
        leading=13,
    )
    skills_style = ParagraphStyle(
        "Skills",
        fontSize=9,
        fontName="Helvetica",
        textColor=colors.black,
        spaceAfter=3,
        leading=14,
    )

    def hr():
        return HRFlowable(
            width="100%",
            thickness=0.5,
            color=colors.HexColor("#1a1a2e"),
            spaceAfter=4,
            spaceBefore=2,
        )

    story = []

    # ── Header ───────────────────────────────────────────────────────────
    story.append(Paragraph("Alex Chen", name_style))
    story.append(Paragraph(
        "San Francisco, CA  •  +1 (415) 555-0192  •  alex.chen.dev@gmail.com  •  "
        "linkedin.com/in/alexchen-swe  •  github.com/alexchen-dev  •  alexchen.dev",
        contact_style,
    ))
    story.append(hr())

    # ── Summary ──────────────────────────────────────────────────────────
    story.append(Paragraph("SUMMARY", section_style))
    story.append(hr())
    story.append(Paragraph(
        "Software Engineer with 3.5 years of experience building scalable backend systems "
        "and developer-facing APIs. Proven track record shipping high-impact features at "
        "Stripe and an early-stage startup. Strong foundation in Python, Go, and TypeScript "
        "with deep expertise in distributed systems, PostgreSQL, and AWS.",
        normal_style,
    ))
    story.append(Spacer(1, 4))

    # ── Experience ───────────────────────────────────────────────────────
    story.append(Paragraph("EXPERIENCE", section_style))
    story.append(hr())

    # Stripe
    story.append(Paragraph("Software Engineer — Stripe", job_title_style))
    story.append(Paragraph("San Francisco, CA  •  January 2023 – Present", job_meta_style))
    stripe_bullets = [
        "Designed and maintained payment reconciliation pipelines processing $2B+ in monthly "
        "transaction volume using Python, Go, and PostgreSQL.",
        "Led migration of legacy monolith services to microservices, reducing p99 latency by 40%.",
        "Built internal developer tooling that reduced on-call incident response time by 30% "
        "across 5 teams.",
        "Collaborated with ML team to integrate fraud detection models into real-time "
        "transaction processing pipeline.",
        "Mentored 2 junior engineers and drove quarterly technical roadmap planning.",
    ]
    for b in stripe_bullets:
        story.append(Paragraph(f"• {b}", bullet_style))
    story.append(Spacer(1, 6))

    # Acme
    story.append(Paragraph("Junior Software Engineer — Acme Technologies", job_title_style))
    story.append(Paragraph("San Francisco, CA  •  June 2021 – December 2022", job_meta_style))
    acme_bullets = [
        "Built full-stack features for a B2B SaaS platform serving 500+ enterprise customers "
        "using React, FastAPI, and PostgreSQL.",
        "Implemented a real-time notification system using WebSockets and Redis Pub/Sub, "
        "handling 10k+ concurrent connections.",
        "Reduced CI/CD pipeline build time by 50% by parallelising test suites and "
        "introducing Docker layer caching.",
        "Shipped 3 major product features end-to-end from design through deployment on AWS ECS.",
    ]
    for b in acme_bullets:
        story.append(Paragraph(f"• {b}", bullet_style))
    story.append(Spacer(1, 4))

    # ── Education ────────────────────────────────────────────────────────
    story.append(Paragraph("EDUCATION", section_style))
    story.append(hr())
    story.append(Paragraph(
        "B.S. Computer Science — University of California, San Diego", job_title_style
    ))
    story.append(Paragraph(
        "September 2017 – June 2021  •  GPA: 3.7 / 4.0", job_meta_style
    ))
    story.append(Spacer(1, 4))

    # ── Skills ───────────────────────────────────────────────────────────
    story.append(Paragraph("SKILLS", section_style))
    story.append(hr())
    skills_lines = [
        "<b>Languages:</b>  Python (Expert)  •  Go (Proficient)  •  "
        "TypeScript (Proficient)  •  JavaScript  •  SQL",
        "<b>Frameworks:</b>  FastAPI  •  React  •  Node.js  •  gRPC",
        "<b>Databases:</b>  PostgreSQL (Expert)  •  Redis  •  DynamoDB",
        "<b>Cloud & Infra:</b>  AWS  •  Docker  •  Kubernetes  •  Terraform",
        "<b>Practices:</b>  System Design  •  Technical Mentorship  •  Agile",
    ]
    for line in skills_lines:
        story.append(Paragraph(line, skills_style))

    doc.build(story)
    print(f"[Resume] Generated: {output_path}")
    return output_path


if __name__ == "__main__":
    generate_alex_chen_resume()
