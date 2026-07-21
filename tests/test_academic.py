from speaker_pipeline.academic import (
    AcademicSource,
    ProfileLink,
    collect_academic,
    discover_profile_links,
    extract_profile,
)
from speaker_pipeline.web import OfficialWebClient


def source():
    return AcademicSource(
        "Example University",
        "https://cs.example.edu/faculty/",
        ("example.edu",),
    )


def test_directory_rejects_staff_and_non_person_links():
    html = """
    <a href='/people/ada-lovelace'>Ada Lovelace</a>
    <a href='/people/restech'>Technical Staff</a>
    <a href='/people/admins'>Administrative Staff</a>
    <a href='/faculty/in-memoriam'>In Memoriam</a>
    <a href='/news'>Faculty Awards</a>
    """
    links = discover_profile_links(html, source())
    assert [(link.name_hint, link.url) for link in links] == [
        ("Ada Lovelace", "https://cs.example.edu/people/ada-lovelace")
    ]


def test_profile_requires_matching_person_title_and_personal_email():
    link = ProfileLink("https://cs.example.edu/people/ada-lovelace", "Ada Lovelace", source())
    html = """
    <nav>robotics privacy databases cloud computing</nav>
    <main>
      <h1>Ada Lovelace: Faculty Home Page</h1>
      <div class='position'>Professor</div>
      <div class='research-interests'>Machine learning and computer vision</div>
      <a href='mailto:ada@cs.example.edu'>Email</a>
      <p>Phone: (617) 555-0101</p>
    </main>
    """
    row = extract_profile(html, link)
    assert row is not None
    assert row["Full Name"] == "Ada Lovelace"
    assert row["Preferred Salutation"] == "Dr. Lovelace"
    assert row["Email"] == "ada@cs.example.edu"
    assert row["Expertise"] == "Machine learning; Computer vision"


def test_profile_rejects_generic_email_or_missing_faculty_title():
    link = ProfileLink("https://cs.example.edu/people/ada-lovelace", "Ada Lovelace", source())
    generic = "<main><h1>Ada Lovelace</h1><p>Professor</p><p>contact@cs.example.edu</p></main>"
    staff = "<main><h1>Ada Lovelace</h1><p>Technical Staff</p><p>ada@cs.example.edu</p></main>"
    assert extract_profile(generic, link) is None
    assert extract_profile(staff, link) is None


def test_collection_isolates_source_failures():
    good = source()
    bad = AcademicSource("Bad University", "https://bad.example.edu/faculty", ("bad.example.edu",))
    pages = {
        good.directory_url: "<a href='/people/ada-lovelace'>Ada Lovelace</a>",
        "https://cs.example.edu/people/ada-lovelace": """
          <main><h1>Ada Lovelace</h1><p>Professor</p>
          <p>Machine learning</p><a href='mailto:ada@cs.example.edu'>Email</a></main>
        """,
    }
    rows, warnings = collect_academic([bad, good], OfficialWebClient(fetcher=pages.__getitem__))
    assert len(rows) == 1
    assert rows[0]["Full Name"] == "Ada Lovelace"
    assert any("Bad University" in warning for warning in warnings)
