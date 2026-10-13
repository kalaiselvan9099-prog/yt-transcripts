import json

from yt_transcripts import formatting as F
from yt_transcripts.backends.base import choose_track
from yt_transcripts.captions import parse_any, parse_vtt
from yt_transcripts.errors import BotCheck, NeedsUpdate, NoCaptions, RateLimited, VideoUnavailable, classify
from yt_transcripts.ids import is_collection, playlist_id, video_id
from yt_transcripts.models import Segment, Transcript


def test_ids():
    assert video_id("https://www.youtube.com/watch?v=CXGGF4ls1JU&t=10") == "CXGGF4ls1JU"
    assert video_id("https://youtu.be/ml50y4RjGiY?si=x") == "ml50y4RjGiY"
    assert video_id("https://www.youtube.com/shorts/ml50y4RjGiY") == "ml50y4RjGiY"
    assert video_id("not a url") is None
    pl = "https://youtube.com/playlist?list=PLNHFjCsTtckI_WnjXe_v9mtfw7x2Ve74K&si=7Oy"
    assert playlist_id(pl) == "PLNHFjCsTtckI_WnjXe_v9mtfw7x2Ve74K" and is_collection(pl)
    assert is_collection("https://www.youtube.com/@SalesforceHelpClub")
    assert not is_collection("https://www.youtube.com/watch?v=CXGGF4ls1JU")


def test_parse_json3_and_vtt_dedupe():
    j = {"events": [{"tStartMs": 0, "dDurationMs": 1000, "segs": [{"utf8": "hello "}, {"utf8": "world"}]},
                    {"tStartMs": 1000, "segs": [{"utf8": "\n"}]},
                    {"tStartMs": 2000, "dDurationMs": 500, "segs": [{"utf8": "a &amp; b"}]}]}
    segs = parse_any(json.dumps(j))
    assert [s.text for s in segs] == ["hello world", "a & b"]
    vtt = ("WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nhello there\n\n"
           "00:00:02.000 --> 00:00:04.000\nhello there\ngeneral <c>kenobi</c>\n")
    assert [s.text for s in parse_vtt(vtt)] == ["hello there", "general kenobi"]
    xml = '<timedtext><body><p t="1000" d="500">hi <s>there</s></p></body></timedtext>'
    assert parse_any(xml)[0].text == "hi there"


def test_choose_track_rules():
    f = [{"ext": "json3", "url": "u"}]
    # original ASR beats a translation bucket of the same language
    lang, kind, _ = choose_track({}, {"en-orig": f, "en": f, "fr": f}, ["en"], True, False)
    assert (lang, kind) == ("en", "auto")
    # manual preferred
    assert choose_track({"en-US": f}, {"en-orig": f}, ["en"], True, False)[1] == "manual"
    # Tamil video, only translated English: take the native Tamil track, not the translation
    lang, kind, _ = choose_track({}, {"ta-orig": f, "en": f}, ["en"], True, False)
    assert (lang, kind) == ("ta", "auto")
    try:
        choose_track({}, {}, ["en"], True, False)
        raise AssertionError
    except NoCaptions:
        pass


def test_classifier(tmp_path):
    assert classify("ERROR: HTTP Error 429: Too Many Requests") is RateLimited
    assert classify("Sign in to confirm you're not a bot") is BotCheck
    assert classify("Video unavailable. This video is private") is VideoUnavailable
    assert classify("PoTokenRequired: blah") is NeedsUpdate
    user = tmp_path / "patterns.toml"
    user.write_text('rate_limited = ["slow down, robot"]\n')
    assert classify("Slow down, robot!", str(user)) is RateLimited


def _t(n=120):
    segs = [Segment(i * 5.0, 5.0, f"line {i} um uh content") for i in range(n)]
    return Transcript("abcdefghijk", "en", "auto", "x", segs, title="T", duration=n * 5.0)


def test_render_and_paginate_lossless():
    t = _t()
    text = F.render(t, every=30)
    assert text.startswith("[0:00] line 0 content line 1")
    assert " um " not in text and " uh " not in text
    assert text.count("[") == 20  # 600s / 30s
    pages, off = [], 0
    while True:
        chunk, nxt = F.paginate(text, off, 300)
        pages.append(chunk)
        assert len(chunk) <= 300
        if nxt is None:
            break
        off = nxt
    assert "\n".join(pages) == text  # nothing lost or duplicated across pages
    ranged = F.render(t, start=F.parse_ts("1:00"), end=F.parse_ts("2:00"), every=30)
    assert ranged.splitlines()[0].startswith("[1:00]") and "line 12 " in ranged and "line 30" not in ranged


def test_search_and_outline():
    t = _t()
    text = F.render(t, every=30)
    ex, hits = F.search(text, "line 55|line 90", context=0)
    assert hits == 2 and "line 55" in ex and "line 90" in ex and "line 10 " not in ex
    o = F.outline(t, section_seconds=300)
    assert len(o) == 2 and o[0]["start"] == "0:00" and o[0]["chars"] > 0
    t.chapters = [{"start": 0, "end": 100, "title": "Intro"}, {"start": 100, "end": 600, "title": "Body"}]
    assert [s["title"] for s in F.outline(t)] == ["Intro", "Body"]
