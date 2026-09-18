"""Choosing which stories and CV bullets the analysis call gets to see.

Tag and alias overlap, no embeddings. The whole profile is roughly 30-60K tokens
against a 1M-token context window, so retrieval focuses the prompt rather than
enabling it. When a match is weak the right answer is to send more stories, not
to retrieve more cleverly - which is why `top_k` is generous and there is a
floor: sending a few extra stories costs a fraction of a cent, while missing the
one story the answer needed defeats the entire tool.

Scoring has two parts. An exact hit between a question tag and a story tag or
alias is worth far more than loose word overlap, because aliases are written
precisely so that a job description's vocabulary routes to the right story. Word
overlap then breaks ties and rescues stories nobody tagged well.

Stubs are ranked alongside filled-in stories on purpose. A stub knows what you
claim even with no STAR detail, which is enough for the feedback to notice you
never said the number on your own CV.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from core.schemas import CvBullet, Profile, Question, Story

TAG_HIT = 6.0
ALIAS_HIT = 5.0
WORD_HIT = 1.0

TOP_STORIES = 6
TOP_BULLETS = 8

STOPWORDS = frozenset("""
a about an and any are as at be been but by can did do does for from had has have
how i if in into is it its me my no not of on one or our out over so some such
than that the their them then there these they this to too us was we were what
when which who why will with would you your tell walk describe time about
""".split())


def tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if w not in STOPWORDS and len(w) > 2}


def _phrases(values: list[str]) -> set[str]:
    return {v.strip().lower() for v in values if v.strip()}


@dataclass
class Scored:
    story: Story
    score: float
    matched: list[str]


def score_story(question: Question, story: Story) -> Scored:
    """How well one story answers one question, and why."""
    q_tags = _phrases(question.tags)
    q_words = tokens(question.text) | {t.replace("-", " ") for t in q_tags}

    matched: list[str] = []
    score = 0.0

    for tag in _phrases(story.tags):
        if tag in q_tags:
            score += TAG_HIT
            matched.append(tag)

    for alias in _phrases(story.aliases):
        if alias in q_tags or alias.replace(" ", "-") in q_tags:
            score += ALIAS_HIT
            matched.append(alias)
        elif tokens(alias) & q_words:
            score += WORD_HIT
            matched.append(alias)

    body = " ".join([story.title, story.claim, story.situation, story.action,
                     story.result, story.reflection])
    overlap = tokens(body) & q_words
    score += WORD_HIT * min(len(overlap), 6)

    return Scored(story=story, score=round(score, 2), matched=matched[:6])


MIN_STORIES = 3


def pick_stories(question: Question, stories: list[Story],
                 top_k: int = TOP_STORIES) -> list[Scored]:
    """The stories worth showing the model, best first.

    Positive scorers first, then padded up to `MIN_STORIES` with the next best
    even when they scored nothing. A question that matches no tags is exactly
    when the model most needs raw material, and returning one thin story - or
    none - guarantees thin feedback. Extra stories cost a fraction of a cent;
    missing the story the answer needed defeats the tool.
    """
    scored = sorted((score_story(question, s) for s in stories),
                    key=lambda s: s.score, reverse=True)
    hits = [s for s in scored if s.score > 0]
    if len(hits) < MIN_STORIES:
        hits = scored[:MIN_STORIES]
    return hits[:top_k]


def pick_bullets(question: Question, profile: Profile,
                 top_k: int = TOP_BULLETS) -> list[CvBullet]:
    """CV bullets relevant to the question, for claims with no story yet."""
    q_tags = _phrases(question.tags)
    q_words = tokens(question.text) | {t.replace("-", " ") for t in q_tags}

    def rank(bullet: CvBullet) -> float:
        score = sum(ALIAS_HIT for a in _phrases(bullet.aliases) if a in q_tags)
        score += WORD_HIT * len(tokens(" ".join(bullet.skills)) & q_words)
        score += WORD_HIT * min(len(tokens(bullet.text) & q_words), 5)
        return score

    bullets = [b for role in profile.roles for b in role.bullets]
    return sorted(bullets, key=rank, reverse=True)[:top_k]
