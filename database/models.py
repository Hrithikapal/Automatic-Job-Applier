"""
database/models.py — SQLAlchemy ORM models.

Six tables:
  users            — personal info, contact, resume path
  work_experiences — job history
  educations       — academic background
  skills           — technical and soft skills
  custom_answers   — key-value store for non-resume form questions
  jobs             — queue and status tracking
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional, List

from sqlalchemy import (
    ForeignKey,
    JSON,
    String,
    Text,
    Float,
    DateTime,
    Boolean,
    func,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    full_name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    phone: Mapped[str] = mapped_column(String(50))
    location: Mapped[str] = mapped_column(String(255))          # "City, State, Country"
    linkedin_url: Mapped[Optional[str]] = mapped_column(String(500))
    github_url: Mapped[Optional[str]] = mapped_column(String(500))
    portfolio_url: Mapped[Optional[str]] = mapped_column(String(500))
    resume_path: Mapped[str] = mapped_column(String(500))       # path to base resume PDF
    summary: Mapped[str] = mapped_column(Text)                  # professional summary

    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    work_experiences: Mapped[List["WorkExperience"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", order_by="WorkExperience.start_date.desc()"
    )
    educations: Mapped[List["Education"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    skills: Mapped[List["Skill"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    custom_answers: Mapped[List["CustomAnswer"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict:
        """Serialize full profile for agent state."""
        return {
            "id": self.id,
            "full_name": self.full_name,
            "email": self.email,
            "phone": self.phone,
            "location": self.location,
            "linkedin_url": self.linkedin_url,
            "github_url": self.github_url,
            "portfolio_url": self.portfolio_url,
            "resume_path": self.resume_path,
            "summary": self.summary,
            "work_experiences": [w.to_dict() for w in self.work_experiences],
            "educations": [e.to_dict() for e in self.educations],
            "skills": [s.to_dict() for s in self.skills],
            "custom_answers": {ca.key: ca.value for ca in self.custom_answers},
        }

    def __repr__(self) -> str:
        return f"<User id={self.id} name={self.full_name!r}>"


# ---------------------------------------------------------------------------
# Work Experience
# ---------------------------------------------------------------------------

class WorkExperience(Base):
    __tablename__ = "work_experiences"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    company: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(255))
    location: Mapped[Optional[str]] = mapped_column(String(255))
    start_date: Mapped[str] = mapped_column(String(10))         # "YYYY-MM"
    end_date: Mapped[Optional[str]] = mapped_column(String(10)) # None = current role
    description: Mapped[str] = mapped_column(Text)              # newline-separated bullets

    user: Mapped["User"] = relationship(back_populates="work_experiences")

    def to_dict(self) -> dict:
        return {
            "company": self.company,
            "title": self.title,
            "location": self.location,
            "start_date": self.start_date,
            "end_date": self.end_date or "Present",
            "description": self.description,
        }

    def __repr__(self) -> str:
        return f"<WorkExperience {self.title!r} at {self.company!r}>"


# ---------------------------------------------------------------------------
# Education
# ---------------------------------------------------------------------------

class Education(Base):
    __tablename__ = "educations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    institution: Mapped[str] = mapped_column(String(255))
    degree: Mapped[str] = mapped_column(String(255))            # "Bachelor of Science"
    field_of_study: Mapped[str] = mapped_column(String(255))    # "Computer Science"
    start_date: Mapped[str] = mapped_column(String(10))
    end_date: Mapped[Optional[str]] = mapped_column(String(10))
    gpa: Mapped[Optional[float]] = mapped_column(Float)

    user: Mapped["User"] = relationship(back_populates="educations")

    def to_dict(self) -> dict:
        return {
            "institution": self.institution,
            "degree": self.degree,
            "field_of_study": self.field_of_study,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "gpa": self.gpa,
        }

    def __repr__(self) -> str:
        return f"<Education {self.degree!r} from {self.institution!r}>"


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------

class Skill(Base):
    __tablename__ = "skills"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(50))
    # programming_language | framework | tool | cloud | soft
    proficiency: Mapped[str] = mapped_column(String(20))
    # expert | proficient | familiar

    user: Mapped["User"] = relationship(back_populates="skills")

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "category": self.category,
            "proficiency": self.proficiency,
        }

    def __repr__(self) -> str:
        return f"<Skill {self.name!r} ({self.proficiency})>"


# ---------------------------------------------------------------------------
# Custom Answers  (the key-value store)
# ---------------------------------------------------------------------------

class CustomAnswer(Base):
    """
    Stores answers to non-resume form questions as key-value pairs.
    Keys are normalized (lowercase, underscored) so the field resolver
    can do fuzzy matching.

    Example keys:
        sponsorship_required, notice_period, salary_expectation,
        willing_to_relocate, heard_about_job, gender, veteran_status,
        disability_status, work_authorization, remote_preference
    """
    __tablename__ = "custom_answers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    key: Mapped[str] = mapped_column(String(255))       # normalized question key
    value: Mapped[str] = mapped_column(Text)            # answer value
    notes: Mapped[Optional[str]] = mapped_column(Text)  # optional human context

    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship(back_populates="custom_answers")

    def __repr__(self) -> str:
        return f"<CustomAnswer {self.key!r}={self.value!r}>"


# ---------------------------------------------------------------------------
# Jobs  (queue + status tracking)
# ---------------------------------------------------------------------------

class JobStatus:
    QUEUED = "queued"
    PROCESSING = "processing"
    SUBMITTED = "submitted"
    FAILED = "failed"
    BACKLOG = "backlog"


class Job(Base):
    """
    Tracks every job URL through the pipeline.

    unanswered_fields stores a JSON list of fields the agent could not fill:
        [{"label": "...", "field_type": "...", "context": "..."}, ...]

    Add these to custom_answers and re-queue to resolve on the next run.
    """
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(String(2000), unique=True)
    company: Mapped[Optional[str]] = mapped_column(String(255))
    title: Mapped[Optional[str]] = mapped_column(String(255))
    ats_platform: Mapped[Optional[str]] = mapped_column(String(50))
    # workday | greenhouse | lever | linkedin | ashby | unknown

    status: Mapped[str] = mapped_column(String(20), default=JobStatus.QUEUED)
    failure_reason: Mapped[Optional[str]] = mapped_column(Text)
    unanswered_fields: Mapped[Optional[dict]] = mapped_column(JSON)
    # list of {label, field_type, context} dicts

    job_description_raw: Mapped[Optional[str]] = mapped_column(Text)
    tailored_resume_text: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    def __repr__(self) -> str:
        return f"<Job id={self.id} status={self.status!r} url={self.url[:50]!r}>"
