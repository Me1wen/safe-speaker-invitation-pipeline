from speaker_pipeline.common import read_table, write_workbook
from speaker_pipeline.schema import CANDIDATE_COLUMNS


def test_review_workbook_round_trip_preserves_exact_schema(tmp_path):
    row = {column: "" for column in CANDIDATE_COLUMNS}
    row.update(
        {
            "Candidate ID": "ACAD-1",
            "Speaker Type": "Academic",
            "Review Status": "Draft",
            "Full Name": "Ada Lovelace",
            "Organization": "Example University",
        }
    )
    path = tmp_path / "review.xlsx"
    write_workbook(path, "Candidates", CANDIDATE_COLUMNS, [row])
    loaded = read_table(path, CANDIDATE_COLUMNS)
    assert loaded == [row]
