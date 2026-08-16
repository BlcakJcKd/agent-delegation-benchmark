from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    output_path: str
    mode: str = "write"


TASKS: tuple[Task, ...] = (
    Task("research_python", "Small research-style Python data analysis", "answer.json"),
    Task("diagnostic_plot", "Matplotlib diagnostic plot", "diagnostic.png"),
    Task("debug_package", "Debug a small Python package", "calcpack"),
    Task("repository_review", "Read-only repository review/testing", "REVIEW.md", "read-only"),
    Task("pandoc_pdf", "Markdown to Pandoc PDF", "report.pdf"),
    Task("scientific_writing", "Scientific Results/Discussion writing", "RESULTS_DISCUSSION.md"),
)


def task_by_id(task_id: str) -> Task:
    for task in TASKS:
        if task.id == task_id:
            return task
    raise KeyError(f"unknown task: {task_id}")


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]
