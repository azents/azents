"""Readable Routine slug normalization contracts."""

import pytest

from azents.repos.routine.definition import routine_slug_base


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Official Releases", "official-releases"),
        ("  Official / Releases___2026! ", "official-releases-2026"),
        ("루틴 배포 검증", "루틴-배포-검증"),
        ("東京 ニュース", "東京-ニュース"),
        ("ＣＩ Check", "ci-check"),
        ("---✨---", "routine"),
        ("A" * 70, "a" * 64),
        ("a" * 63 + " -more", "a" * 63),
    ],
)
def test_slug_preserves_readable_title_with_bounded_normalization(
    title: str, expected: str
) -> None:
    assert routine_slug_base(title) == expected
